"""
Tests for pipeline/property.py::enrich_property — the per-ZIP paid detail step.

Everything external is monkeypatched (DB fetch/upsert, audit writes, HTTP), in
the same style as tests/test_backfill.py, so these stay pure/offline. Two
behaviours are locked in here:

1. Fill-only: upsert_properties overwrites any non-None column it is handed
   (SET col = EXCLUDED.col), so the step itself must drop fields the row
   already holds — otherwise a row queued for one gap gets its HCAD assessor
   facts replaced by the vendor's copy.

2. Shadow parcel verification: an accepted record whose assessorID disagrees
   with the row's stored parcel number is still applied, but the disagreement
   is counted and recorded to property_field_audits — measure the address
   check's false-accept rate before same_parcel becomes a gate.
"""
from datetime import date
from types import SimpleNamespace

import pytest

import pipeline.property as prop


def _row(**over):
    row = {
        "id": 101, "address": "123 Main St", "zip": "77396",
        "parcel_apn": None, "year_built": None, "square_footage": None,
        "lot_size": None, "property_type": None, "estimated_value": None,
        "estimated_equity": None, "last_sale_date": None, "last_sale_price": None,
        "owner_name": None, "owner_occupied": None, "ownership_years": None,
        "garage_spaces": None, "garage_type": None,
    }
    row.update(over)
    return row


PAYLOAD = [{
    "addressLine1": "123 Main St",
    "yearBuilt": 1998,
    "squareFootage": 2100,
    "assessorID": "066-064-013-0020",
    "taxAssessments": {"2024": {"year": 2024, "value": 320_000}},
    "owner": {"names": ["JANE DOE"], "type": "Individual"},
    "features": {"garageSpaces": 2, "garageType": "Attached"},
}]


@pytest.fixture
def run_enrich(monkeypatch):
    """Factory: run_enrich(rows, payload, answered=True) -> (counters, writes, audits)."""
    def factory(rows, payload, answered=True):
        writes: list[list[dict]] = []
        audits: list[list[tuple]] = []

        monkeypatch.setattr(prop, "_SOURCE_CONFIG", {
            "rentcast": {"key": "test-key", "flag": {"property": "rentcast"},
                         "delay": 0, "cap": None},
        })
        monkeypatch.setattr(prop, "PROPERTY_FIELD_SOURCES", ["rentcast"])
        monkeypatch.setattr(prop, "get_conn",
                            lambda: SimpleNamespace(close=lambda: None))
        monkeypatch.setattr(prop, "fetch_missing_any",
                            lambda *a, **k: [dict(r) for r in rows])
        monkeypatch.setattr(prop, "upsert_properties",
                            lambda conn, rows_, acct: (writes.append(rows_), len(rows_))[1])
        monkeypatch.setattr(prop, "record_findings",
                            lambda conn, acct, findings: audits.append(findings))
        monkeypatch.setattr(prop, "get_json_result",
                            lambda *a, **k: (payload, answered))

        counters = prop.enrich_property("77396", account_id=1)
        return counters["rentcast"], writes[0] if writes else [], \
            audits[0] if audits else []

    return factory


# ── Request shape ─────────────────────────────────────────────────────────────
# Measured against the live API, on one address RentCast demonstrably holds:
#   address + zipCode          -> 404      address + state + zipCode -> 200
#   address + city + zipCode   -> 404      address + state (no zip)  -> 200
# Every 200 carries `state`; every 404 omits it. Sending the row's state is the
# whole difference between this step working and returning 0 matches for a
# whole ZIP, so it is asserted rather than left to inspection.

def test_state_is_sent_to_the_vendor(monkeypatch):
    """Regression: omitting `state` 404s even for addresses RentCast holds —
    a 500-property run of ZIP 77007 reported 0 ok / 181 fail because of it."""
    seen = {}

    def _capture(url, **kwargs):
        seen.update(kwargs.get("params") or {})
        return None, True

    monkeypatch.setattr(prop, "get_json_result", _capture)
    prop._rentcast_detail("123 Main St", "77396", "TX")
    assert seen["state"] == "TX"
    assert seen["address"] == "123 Main St"
    assert seen["zipCode"] == "77396"


def test_missing_state_is_omitted_rather_than_sent_empty(monkeypatch):
    """A row with no state still gets asked — an empty `state=` parameter
    would be a different request than sending none at all."""
    seen = {}

    def _capture(url, **kwargs):
        seen.update(kwargs.get("params") or {})
        return None, True

    monkeypatch.setattr(prop, "get_json_result", _capture)
    prop._rentcast_detail("123 Main St", "77396", None)
    assert "state" not in seen


def test_enrich_passes_each_row_state_through(run_enrich, monkeypatch):
    """The step must forward the row's own state, not a constant: an account
    holding rows in two states would otherwise query them all as one."""
    seen = []
    monkeypatch.setattr(prop, "_rentcast_detail",
                        lambda addr, zc, st=None: (seen.append(st), (None, True))[1])
    monkeypatch.setattr(prop, "_SOURCE_CONFIG", {
        "rentcast": {"key": "k", "flag": {}, "delay": 0, "cap": None}})
    monkeypatch.setattr(prop, "PROPERTY_FIELD_SOURCES", ["rentcast"])
    monkeypatch.setattr(prop, "get_conn",
                        lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(prop, "fetch_missing_any", lambda *a, **k: [
        {**_row(), "state": "TX"}, {**_row(id=102), "state": "FL"}])
    monkeypatch.setattr(prop, "upsert_properties", lambda c, r, a: len(r))
    monkeypatch.setattr(prop, "record_findings", lambda *a: None)

    prop.enrich_property("77396", account_id=1)
    assert seen == ["TX", "FL"]


# ── Fill-only ─────────────────────────────────────────────────────────────────

def test_fields_the_row_already_has_are_not_written(run_enrich):
    """The core guarantee: HCAD ran first and free — the paid source must not
    hand its copy of an already-filled field to the overwriting upsert."""
    counter, writes, _ = run_enrich(
        [_row(year_built=1960, estimated_value=234_193)], PAYLOAD)
    written = writes[0]
    assert "year_built" not in written          # HCAD's value survives
    assert "estimated_value" not in written     # tot_appr_val survives
    assert written["square_footage"] == 2100    # genuine gap, filled
    assert written["garage_spaces"] == 2
    assert counter["ok"] == 1


def test_a_fully_answered_row_is_still_stamped(run_enrich):
    """Even when every mapped field is already filled, the row was matched and
    billed — it must carry the checked stamp and the source flag so it leaves
    the queue."""
    full = _row(year_built=1998, square_footage=2100, property_type="x",
                estimated_value=1, estimated_equity=1, last_sale_date="2015-06-01",
                last_sale_price=1, owner_name="X", owner_occupied=True,
                ownership_years=1, garage_spaces=2, garage_type="Attached",
                parcel_apn="0660640130020")
    counter, writes, _ = run_enrich([full], PAYLOAD)
    written = writes[0]
    assert counter["ok"] == 1
    assert written["enrichment_flags"]["property"] == "rentcast"
    assert "rentcast_checked" in written["enrichment_flags"]
    assert "year_built" not in written


def test_filled_derived_fields_track_the_rows_own_basis(run_enrich):
    """A kept 2005 sale date must not sit beside tenure counted from the
    vendor's 2019 sale — derived fields are recomputed against the row."""
    payload = [dict(PAYLOAD[0], lastSaleDate="2019-08-20")]
    counter, writes, _ = run_enrich(
        [_row(last_sale_date="2005-03-01")], payload)
    written = writes[0]
    assert "last_sale_date" not in written              # row keeps its own
    assert written["ownership_years"] == date.today().year - 2005


def test_no_record_stamps_without_source_flag(run_enrich):
    counter, writes, _ = run_enrich([_row()], None)
    written = writes[0]
    assert counter["fail"] == 1
    assert "rentcast_checked" in written["enrichment_flags"]
    assert "property" not in written["enrichment_flags"]


def test_unanswered_rows_are_left_unstamped(run_enrich):
    counter, writes, audits = run_enrich([_row()], None, answered=False)
    assert counter["unanswered"] == 1
    assert writes == []
    assert audits == []


# ── Shadow parcel verification ────────────────────────────────────────────────

def test_agreeing_parcel_records_nothing(run_enrich):
    counter, _, audits = run_enrich(
        [_row(parcel_apn="0660640130020")], PAYLOAD)
    assert counter["parcel_mismatch"] == 0
    assert audits == []


def test_disagreeing_parcel_is_recorded_but_still_applied(run_enrich):
    """Shadow mode: observe before enforcing. The data lands (the address echo
    accepted it), but the disagreement is measurable in the audit trail."""
    counter, writes, audits = run_enrich(
        [_row(parcel_apn="9990001112223")], PAYLOAD)
    assert counter["parcel_mismatch"] == 1
    (property_id, finding), = audits
    assert property_id == 101
    assert finding["field"] == "parcel_apn"
    assert finding["stored"] == "9990001112223"
    assert finding["remote"] == "0660640130020"
    assert finding["resolution"] == "kept"
    # Still applied — and the stored parcel number is not overwritten (it is
    # non-NULL, so the fill-only filter drops the vendor's).
    written = writes[0]
    assert written["square_footage"] == 2100
    assert "parcel_apn" not in written


def test_missing_stored_parcel_is_filled_not_flagged(run_enrich):
    counter, writes, audits = run_enrich([_row()], PAYLOAD)
    assert counter["parcel_mismatch"] == 0
    assert audits == []
    assert writes[0]["parcel_apn"] == "0660640130020"
