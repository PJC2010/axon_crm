"""Tests for pipeline/backfill.py — candidate selection and sweep bookkeeping.

The DB and the RentCast provider are stubbed, so these exercise the parts that
decide what gets queried and what gets written — the parts that spend money.
"""
from datetime import date, timedelta
from typing import NamedTuple

import pytest

from pipeline import backfill
from pipeline.backfill import CANDIDATE_FIELDS, CHECKED_FLAG, _due_for_check, _gaps


def _iso(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def _row(**overrides) -> dict:
    row = {"id": 1, "address": "123 Main St", "zip": "77396",
           "year_built": 1998, "square_footage": 2100, "lot_size": 7200,
           "property_type": "Single Family", "estimated_value": 340_000,
           "estimated_equity": 150_000, "last_sale_date": "2015-06-01",
           "last_sale_price": 250_000, "owner_name": "JANE DOE",
           "owner_occupied": True, "ownership_years": 10,
           "garage_spaces": 2, "garage_type": "Attached",
           "enrichment_flags": {}}
    row.update(overrides)
    return row


# ── Cooldown: the guard against re-billing the same address forever ───────────

def test_never_checked_row_is_due():
    assert _due_for_check(_row(), 90) is True


def test_row_inside_the_window_is_not_due():
    row = _row(enrichment_flags={CHECKED_FLAG: _iso(10)})
    assert _due_for_check(row, 90) is False


def test_row_past_the_window_is_due_again():
    row = _row(enrichment_flags={CHECKED_FLAG: _iso(100)})
    assert _due_for_check(row, 90) is True


def test_zero_recheck_days_means_ask_once_ever():
    row = _row(enrichment_flags={CHECKED_FLAG: _iso(3650)})
    assert _due_for_check(row, 0) is False
    # …but a row never asked about still gets its first look.
    assert _due_for_check(_row(), 0) is True


def test_missing_flags_column_is_treated_as_never_checked():
    assert _due_for_check({"enrichment_flags": None}, 90) is True
    assert _due_for_check({}, 90) is True


# ── Gap detection ─────────────────────────────────────────────────────────────

def test_fully_populated_row_has_no_gap():
    assert _gaps(_row()) == []


def test_only_fillable_fields_count_as_gaps():
    # contact_phone is a skip-trace field, not something RentCast supplies, so a
    # row missing only that must not earn a property lookup.
    row = _row(year_built=None, garage_type=None, contact_phone=None)
    assert _gaps(row) == ["year_built", "garage_type"]


def test_candidate_fields_never_include_paid_contact_data():
    """A gap in skip-traced or demographic data is a different vendor's job."""
    for field in ("contact_phone", "contact_email", "owner_age", "credit_rating"):
        assert field not in CANDIDATE_FIELDS


def test_audit_gap_clause_excludes_no_situs_rows():
    """The audit's gap_rows/eligible must equal the sweep's candidate pool.
    fetch_missing_any excludes no-situs parcels, so the gap clause must too, or
    the audit promises lookups the sweep never makes."""
    from pipeline.backfill import _gap_clause
    assert "!~ '^0+(\\s|$)'" in _gap_clause()


# ── Sweep ─────────────────────────────────────────────────────────────────────

class _StubProvider:
    """Stands in for RentCastProvider, counting calls so cost is assertable.

    `answered=False` simulates an outage — the vendor never responded — which is
    a different thing from answering "no record for this address".
    """

    def __init__(self, record: dict | None, answered: bool = True):
        self.record = record
        self.answered = answered
        self.calls: list[tuple[str, str, str | None]] = []

    def get_by_address(self, address, zip_code=None, state=None):
        return self.get_by_address_result(address, zip_code, state)[0]

    def get_by_address_result(self, address, zip_code=None, state=None):
        self.calls.append((address, zip_code, state))
        return self.record, self.answered


class _StubConn:
    pass


@pytest.fixture
def stub_sweep(monkeypatch):
    """Wire up backfill.sweep against in-memory rows and a stub provider.

    Returns a factory: `run(rows, record, **kwargs) -> (counter, provider, writes)`.
    """
    def factory(rows, record, answered=True, **kwargs):
        provider = _StubProvider(record, answered=answered)
        writes: list[list[dict]] = []
        audits: list[list[tuple]] = []
        queries: list[dict] = []

        def _fetch(conn, fields, account_id, zip_code=None, **kw):
            queries.append({"fields": fields, "account_id": account_id,
                            "zip_code": zip_code, **kw})
            # Selection, ordering and capping happen in SQL (see
            # tests/test_db.py); the stub returns what the query would.
            return [dict(r) for r in rows][:kw.get("limit") or len(rows)]

        monkeypatch.setattr(backfill, "RENTCAST_API_KEY", "test-key")
        monkeypatch.setattr(backfill, "PROPERTY_BACKFILL_DELAY", 0)
        monkeypatch.setattr(backfill, "fetch_missing_any", _fetch)
        monkeypatch.setattr(backfill, "upsert_properties",
                            lambda conn, rows_, acct: (writes.append(rows_), len(rows_))[1])
        monkeypatch.setattr(backfill, "record_findings",
                            lambda conn, acct, findings: audits.append(findings))
        monkeypatch.setattr("pipeline.property_provider.get_provider",
                            lambda name=None: provider)

        counter = backfill.sweep(_StubConn(), 1, **kwargs)
        return _Result(counter, provider, writes[0] if writes else [],
                       audits[0] if audits else [], queries[0] if queries else {})

    return factory


class _Result(NamedTuple):
    counter: dict
    provider: _StubProvider
    writes: list
    audits: list
    query: dict


RECORD = {
    "addressLine1": "123 Main St",
    "yearBuilt": 1998, "squareFootage": 2100, "lotSize": 7200,
    "propertyType": "Single Family", "subdivision": "Summerwood",
    "price": 340_000, "lastSalePrice": 250_000, "lastSaleDate": "2015-06-01",
    "ownerOccupied": True, "owner": {"names": ["JANE DOE"]},
    "features": {"garageSpaces": 2, "garageType": "Attached"},
    "latitude": 29.9, "longitude": -95.2, "city": "Houston", "state": "TX",
}


def test_no_api_key_spends_nothing(stub_sweep, monkeypatch):
    monkeypatch.setattr(backfill, "RENTCAST_API_KEY", "")
    counter = backfill.sweep(_StubConn(), 1)
    assert counter["skipped_no_key"] is True
    assert counter["candidates"] == 0


def test_dry_run_makes_no_api_calls_and_writes_nothing(stub_sweep):
    r = stub_sweep([_row(year_built=None, garage_type=None)], RECORD, dry_run=True)
    assert r.provider.calls == []
    assert r.writes == []
    assert r.counter["candidates"] == 1
    assert r.counter["queried"] == 0
    # The per-field breakdown reports the standing gap — the ceiling on what a
    # real sweep could fill.
    assert r.counter["by_field"]["year_built"]["filled"] == 1
    assert r.counter["by_field"]["garage_type"]["filled"] == 1


def test_fill_writes_only_into_nulls(stub_sweep):
    """The core guarantee: an existing value is never touched in fill mode."""
    r = stub_sweep([_row(year_built=None, estimated_value=200_000)], RECORD)
    written = r.writes[0]
    assert written["year_built"] == 1998
    assert "estimated_value" not in written    # disagreed, but kept
    assert r.counter["fields_filled"] >= 1
    assert r.counter["mismatches"] >= 1
    assert r.counter["fields_refreshed"] == 0


def test_refresh_mode_updates_the_stale_market_value(stub_sweep):
    r = stub_sweep([_row(estimated_value=200_000)], RECORD, mode="refresh")
    assert r.writes[0]["estimated_value"] == 340_000
    assert r.counter["fields_refreshed"] == 1


def test_every_queried_row_is_stamped_even_without_a_match(stub_sweep):
    """Otherwise a field RentCast structurally cannot supply — a sale price in a
    non-disclosure state — keeps the row eligible and re-bills it forever."""
    r = stub_sweep([_row(last_sale_price=None)], None)   # provider finds nothing
    assert len(r.provider.calls) == 1
    assert r.counter["queried"] == 1
    assert r.counter["matched"] == 0
    assert r.writes[0]["enrichment_flags"] == {CHECKED_FLAG: date.today().isoformat()}


def test_an_outage_leaves_rows_eligible_instead_of_burning_them(stub_sweep):
    """A vendor timeout must not stamp the row. Stamping an unanswered lookup
    would let one bad afternoon disqualify a whole batch from being retried for
    PROPERTY_RECHECK_DAYS — the opposite of what the sweep is for."""
    rows = [_row(id=i, address=f"{i} Main St", year_built=None) for i in range(3)]
    r = stub_sweep(rows, None, answered=False)
    assert r.counter["unanswered"] == 3
    assert r.counter["queried"] == 0
    assert r.writes == []          # nothing stamped, so all three stay eligible


def test_a_clean_no_record_is_still_stamped(stub_sweep):
    """The other side of the same coin: an address the vendor genuinely has no
    record of must be stamped, or it is re-billed on every future run."""
    r = stub_sweep([_row(year_built=None)], None, answered=True)
    assert r.counter["queried"] == 1
    assert r.counter["unanswered"] == 0
    assert r.writes[0]["enrichment_flags"] == {CHECKED_FLAG: date.today().isoformat()}


def test_matched_row_carries_the_provenance_marker(stub_sweep):
    r = stub_sweep([_row(year_built=None)], RECORD)
    assert r.writes[0]["enrichment_flags"] == {
        CHECKED_FLAG: date.today().isoformat(), "property": "rentcast",
    }


# ── Candidate selection is delegated to SQL ───────────────────────────────────
# Ordering and capping live in fetch_missing_any so an account-wide sweep never
# pulls the whole book into memory; tests/test_db.py covers the SQL itself.
# These assert the sweep hands it the right arguments.

def test_the_cap_is_pushed_into_the_query(stub_sweep):
    rows = [_row(id=i, address=f"{i} Main St", year_built=None) for i in range(10)]
    r = stub_sweep(rows, RECORD, limit=3)
    assert r.query["limit"] == 3
    assert r.counter["candidates"] == 3
    assert len(r.provider.calls) == 3


def test_the_query_asks_only_about_fields_rentcast_can_fill(stub_sweep):
    r = stub_sweep([_row(year_built=None)], RECORD)
    assert r.query["fields"] == CANDIDATE_FIELDS
    assert r.query["checked_flag"] == CHECKED_FLAG


def test_the_query_is_scoped_to_the_account_and_optional_zip(stub_sweep):
    r = stub_sweep([_row(year_built=None)], RECORD, zip_code="77396")
    assert r.query["account_id"] == 1
    assert r.query["zip_code"] == "77396"


def test_the_default_cap_applies_when_none_is_given(stub_sweep, monkeypatch):
    """An unbounded account-wide sweep would be an unbounded bill."""
    monkeypatch.setattr(backfill, "PROPERTY_BACKFILL_MAX", 42)
    r = stub_sweep([_row(year_built=None)], RECORD)
    assert r.query["limit"] == 42


def test_zero_limit_spends_nothing(stub_sweep):
    r = stub_sweep([_row(year_built=None)], RECORD, limit=0)
    assert r.provider.calls == []
    assert r.counter["candidates"] == 0


def test_cancellation_keeps_what_was_already_paid_for(stub_sweep):
    rows = [_row(id=i, address=f"{i} Main St", year_built=None) for i in range(5)]
    calls = {"n": 0}

    def should_stop():
        calls["n"] += 1
        return calls["n"] > 2      # stop before the third property

    r = stub_sweep(rows, RECORD, should_stop=should_stop)
    assert r.counter["cancelled"] is True
    assert len(r.provider.calls) == 2
    assert len(r.writes) == 2      # both completed lookups were persisted


def test_discrepancies_are_recorded_for_review(stub_sweep):
    r = stub_sweep([_row(year_built=1975)], RECORD)
    fields = {finding["field"]: finding for _, finding in r.audits}
    assert fields["year_built"]["stored"] == "1975"
    assert fields["year_built"]["remote"] == "1998"
    assert fields["year_built"]["resolution"] == "kept"


def test_location_noise_is_not_reported_as_a_discrepancy(stub_sweep):
    """A coordinate a few metres off is not a finding worth a row in the report."""
    r = stub_sweep([_row(latitude=29.90001, city="HOUSTON")], RECORD)
    assert all(f["field"] not in ("latitude", "city") for _, f in r.audits)


def test_matching_row_produces_no_findings(stub_sweep):
    r = stub_sweep([_row(subdivision="Summerwood")], RECORD)
    assert r.audits == []
    assert r.counter["mismatches"] == 0
    assert r.counter["fields_filled"] == 0


def test_bad_mode_is_rejected():
    with pytest.raises(ValueError):
        backfill.sweep(_StubConn(), 1, mode="overwrite")


# ── audit ─────────────────────────────────────────────────────────────────────
# The audit counts in SQL rather than in Python, building column fragments by
# interpolation. These assert on the statements it emits.

class _AuditCursor:
    def __init__(self, sink):
        self.sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        self.sink.append({"sql": " ".join(sql.split()), "params": list(params)})

    def fetchone(self):
        # Enough of a row for audit() to format: every counted column plus totals.
        row = {f: 0 for f in backfill._TRACKED}
        row.update({"total": 0, "gap_rows": 0, "eligible": 0})
        return row

    def fetchall(self):
        return []


class _AuditConn:
    def __init__(self):
        self.queries: list[dict] = []

    def cursor(self, **kwargs):
        return _AuditCursor(self.queries)


def _audit_queries(**kwargs) -> list[dict]:
    conn = _AuditConn()
    backfill.audit(conn, 7, **kwargs)
    return conn.queries


def test_every_placeholder_has_exactly_one_parameter():
    """A miscounted or misordered param list silently asks a different question —
    psycopg2 binds positionally, in the order placeholders appear in the text."""
    for query in _audit_queries(zip_code="77396"):
        assert query["sql"].count("%s") == len(query["params"]), query["sql"]


def test_cooldown_params_bind_before_the_scope_params():
    """The FILTER clause sits in the SELECT list, ahead of the WHERE."""
    totals = _audit_queries(zip_code="77396", recheck_days=90)[0]
    assert totals["params"] == [CHECKED_FLAG, CHECKED_FLAG, 90, 7, "77396"]


def test_audit_is_scoped_to_the_account_in_every_query():
    for query in _audit_queries():
        assert "account_id = %s" in query["sql"]
        assert 7 in query["params"]


def test_audit_makes_no_api_calls(monkeypatch):
    """It runs behind a UI page load — it must never be able to spend money."""
    def _boom(*a, **kw):                       # pragma: no cover - failure path
        raise AssertionError("audit must not call a paid provider")
    monkeypatch.setattr("pipeline.property_provider.get_provider", _boom)
    _audit_queries()


def test_audit_reports_zero_without_dividing_by_zero():
    """A brand-new account has no properties at all."""
    report = backfill.audit(_AuditConn(), 7)
    assert report["properties"] == 0
    assert report["rentcast"]["eligible"] == 0
    assert all(r["pct"] == 0.0 for r in report["fields"].values())


# ── Vendor answered about the wrong property ──────────────────────────────────
# RentCast resolves the address string itself and limit=1 hides any ambiguity,
# so a lookup can come back describing a neighbouring parcel. Writing that would
# put a stranger's year built, value and owner on the lead — and stamp it as
# enriched, so nothing would ever look again.

def test_a_wrong_property_is_rejected_not_written(stub_sweep):
    wrong = {**RECORD, "addressLine1": "125 Main St"}
    r = stub_sweep([_row(year_built=None)], wrong)
    written = r.writes[0]
    assert "year_built" not in written          # the stranger's data is not stored
    assert r.counter["address_mismatch"] == 1
    assert r.counter["matched"] == 0


def test_a_wrong_property_is_still_stamped(stub_sweep):
    """Asking again tomorrow returns the same wrong answer, so the row is
    stamped; the recheck window is what eventually retries it."""
    r = stub_sweep([_row(year_built=None)], {**RECORD, "addressLine1": "125 Main St"})
    assert r.writes[0]["enrichment_flags"] == {CHECKED_FLAG: date.today().isoformat()}
    assert "property" not in r.writes[0]["enrichment_flags"]


def test_a_wrong_property_is_recorded_for_review(stub_sweep):
    """It lands in the same report as field discrepancies, under `address` —
    it is the finding an operator most needs to see."""
    r = stub_sweep([_row(year_built=None)], {**RECORD, "addressLine1": "125 Main St"})
    (_, finding), = r.audits
    assert finding["field"] == "address"
    assert finding["stored"] == "123 Main St"
    assert finding["remote"] == "125 Main St"


def test_address_is_auditable_but_never_a_paid_candidate(stub_sweep):
    """It may appear in the trail, but a NULL address must not earn a lookup."""
    assert "address" in backfill.AUDITED_FIELDS
    assert "address" not in CANDIDATE_FIELDS


def test_a_differently_formatted_same_address_is_accepted(stub_sweep):
    """Verification must not reject on formatting — a false negative silently
    throws away data already paid for."""
    r = stub_sweep([_row(year_built=None)], {**RECORD, "addressLine1": "123 MAIN STREET"})
    assert r.counter["address_mismatch"] == 0
    assert r.counter["matched"] == 1
    assert r.writes[0]["year_built"] == 1998


def test_sweep_sends_the_row_state_to_the_vendor(stub_sweep):
    """Regression: the sweep omitted `state`, and RentCast 404s a lookup
    without it — even for an address it returns from its own ZIP scan. That
    is why a 181-row sweep reported 0 matches and stamped every row as
    'checked, nothing there'."""
    r = stub_sweep([_row(year_built=None, state="TX")], RECORD)
    assert r.provider.calls, "no lookup was made"
    address, zip_code, state = r.provider.calls[0]
    assert address == "123 Main St"
    assert zip_code == "77396"
    assert state == "TX", f"state not forwarded: {r.provider.calls[0]!r}"
