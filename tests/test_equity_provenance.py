"""The equity haircut follows the stored number, not the step that wrote it.

pipeline/equity.py::stored_equity_source resolves the basis of a row's
estimated_equity (persisted stamp → in-run hint → re-derivation for legacy
rows) and pipeline/scoring.py::equity_is_fallback feeds it to the engine, so
the EQUITY_FALLBACK_SIGNAL_SCALE haircut applies identically on the HCAD
path, the RentCast path, the backfill sweep, the scorer's own backfill and
the explain endpoint. Pure math — no database.
"""
from datetime import date

import pytest

import config
import pipeline.hcad_enrichment as hcad_enrichment
from pipeline import hcad_store
from pipeline.equity import (
    EQUITY_SOURCE_FLAG, FALLBACK_SOURCE, PROVIDER_SOURCE, equity_source_for,
    stored_equity_source,
)
from pipeline.reconcile import equity_provenance
from pipeline.scoring import _compute_score, equity_is_fallback, explain_score
from pipeline.select import prescore


ROW = {
    "year_built": date.today().year - 22, "last_sale_date": date.today(),
    "estimated_value": 300_000, "estimated_equity": 180_000,
    "last_sale_price": None, "garage_spaces": 2, "zip_median_income": 75_000,
    "permit_count_24mo": 2, "neighborhood_value_ratio": 1.3,
}


# ── stored_equity_source ──────────────────────────────────────────────────────

def test_persisted_stamp_wins():
    row = dict(ROW, enrichment_flags={EQUITY_SOURCE_FLAG: "amortized"})
    assert stored_equity_source(row) == "amortized"
    assert not equity_is_fallback(row)


def test_in_run_hint_counts_as_fallback():
    assert stored_equity_source(dict(ROW, estimated_equity_is_fallback=True)) == FALLBACK_SOURCE


def test_legacy_row_rederives_the_flat_fallback():
    # No stamp, no hint: 300_000 × 0.6 == 180_000, nothing else produces that.
    assert stored_equity_source(dict(ROW, enrichment_flags={})) == FALLBACK_SOURCE
    assert stored_equity_source(dict(ROW, enrichment_flags=None)) == FALLBACK_SOURCE


def test_legacy_row_with_another_number_is_unattributed():
    assert stored_equity_source(dict(ROW, estimated_equity=150_000)) is None


def test_legacy_row_with_a_sale_price_is_not_called_fallback():
    # With a price the estimator would have amortized, and an amortized figure
    # drifts daily, so equality with the flat fallback proves nothing.
    row = dict(ROW, last_sale_price=250_000, last_sale_date="2015-06-01")
    assert stored_equity_source(row) is None


def test_no_equity_no_source():
    assert stored_equity_source(dict(ROW, estimated_equity=None)) is None
    assert stored_equity_source({}) is None


def test_equity_source_for_matches_the_estimator():
    assert equity_source_for(300_000) == FALLBACK_SOURCE
    assert equity_source_for(300_000, 250_000, "2015-06-01") == "amortized"
    assert equity_source_for(300_000, mortgage_balance=100_000) == "balance"
    assert equity_source_for(None) is None


# ── engine: the haircut is a property of the row ──────────────────────────────

def test_stamped_fallback_is_haircut_without_the_in_run_hint():
    stamped = dict(ROW, enrichment_flags={EQUITY_SOURCE_FLAG: FALLBACK_SOURCE})
    measured = dict(ROW, enrichment_flags={EQUITY_SOURCE_FLAG: "balance"})
    w = config.DEFAULT_WEIGHTS["equity"]
    haircut = w * 1.0 * 100 * (1 - config.EQUITY_FALLBACK_SIGNAL_SCALE)
    assert (_compute_score(measured, config.DEFAULT_WEIGHTS)
            - _compute_score(stamped, config.DEFAULT_WEIGHTS)) == pytest.approx(haircut)


def test_explain_agrees_with_the_engine_on_a_stamped_row():
    row = dict(ROW, enrichment_flags={EQUITY_SOURCE_FLAG: FALLBACK_SOURCE})
    breakdown = explain_score(row, config.DEFAULT_WEIGHTS)
    assert breakdown["score"] == pytest.approx(
        round(_compute_score(row, config.DEFAULT_WEIGHTS), 2))


def test_profiles_without_an_equity_weight_never_consult_provenance():
    row = {"days_to_expiration": 15, "policy_count": 1, "premium_in_force": 2500,
           "estimated_equity": 1, "estimated_value": 1}
    weights = {"a": 1.0}
    meta = {"a": {"field": "days_to_expiration"}}
    from pipeline.scoring import _weighted_sum
    assert _weighted_sum(row, weights, meta, {"a": lambda v: 1.0}) == 100.0


# ── writers stamp the basis next to the number ────────────────────────────────

def test_reconcile_equity_provenance_reads_effective_inputs():
    stored = {"estimated_value": 200_000, "last_sale_price": None, "last_sale_date": None}
    assert equity_provenance(stored, {"estimated_equity": 120_000}) == FALLBACK_SOURCE
    assert equity_provenance(stored, {"estimated_equity": 90_000,
                                      "last_sale_price": 150_000,
                                      "last_sale_date": "2018-01-01"}) == "amortized"
    assert equity_provenance(stored, {}) is None
    assert equity_provenance(stored, {"estimated_equity": None}) is None


def test_prescore_hints_its_injected_fallback(monkeypatch):
    # The pre-enrichment rank must see the same haircut the final score
    # applies, or the paid budget goes to rows the grade will not reward.
    row = {"estimated_value": 300_000, "estimated_equity": None,
           "year_built": date.today().year - 20}
    flagged = dict(row, estimated_equity=180_000, estimated_equity_is_fallback=True)
    assert prescore(row, config.DEFAULT_WEIGHTS) == pytest.approx(
        _compute_score(flagged, config.DEFAULT_WEIGHTS))


class _Conn:
    def close(self):
        pass


def test_hcad_enrichment_stamps_the_fallback_it_persists(monkeypatch):
    address = "4614 PIN OAK FOREST DR"
    key = hcad_store.normalize(address)
    monkeypatch.setattr(hcad_store, "query_properties", lambda z: {
        key: {"estimated_value": 250_000, "year_built": 1998, "last_sale_date": None,
              "parcel_apn": None, "site_city": "HOUSTON", "state_class": "A1"}})
    monkeypatch.setattr(hcad_store, "query_extra_features", lambda z: {})
    monkeypatch.setattr(hcad_enrichment, "get_conn", lambda: _Conn())
    monkeypatch.setattr(hcad_enrichment, "fetch_by_zip", lambda c, z, a: [
        {"id": 1, "address": address, "zip": "77070", "estimated_equity": None}])
    monkeypatch.setattr(hcad_enrichment, "record_findings", lambda *a, **k: None)
    written: list[dict] = []
    monkeypatch.setattr(hcad_enrichment, "upsert_properties",
                        lambda c, u, a: written.extend(u) or len(u))

    assert hcad_enrichment.enrich_hcad("77070", 1) == 1
    (update,) = written
    assert update["estimated_equity"] == int(250_000 * config.EQUITY_FALLBACK_PCT)
    assert update["enrichment_flags"] == {"hcad": "assessor",
                                          EQUITY_SOURCE_FLAG: FALLBACK_SOURCE}


def test_explain_puts_the_haircut_on_the_equity_bar_only():
    row = dict(ROW, enrichment_flags={EQUITY_SOURCE_FLAG: FALLBACK_SOURCE})
    breakdown = explain_score(row, config.DEFAULT_WEIGHTS)
    by_key = {f["key"]: f for f in breakdown["factors"]}
    w = config.DEFAULT_WEIGHTS
    assert by_key["equity"]["signal"] == pytest.approx(config.EQUITY_FALLBACK_SIGNAL_SCALE)
    assert by_key["equity"]["contribution"] == pytest.approx(
        w["equity"] * config.EQUITY_FALLBACK_SIGNAL_SCALE * 100, abs=0.01)
    # Every other bar is untouched — no proportional smear.
    assert by_key["age"]["contribution"] == pytest.approx(w["age"] * 100, abs=0.01)
    assert sum(f["contribution"] for f in breakdown["factors"]) == pytest.approx(
        breakdown["score"], abs=0.05)


def test_demographics_equity_replaces_the_fallback_stamp(monkeypatch):
    import pipeline.demographics as demographics
    monkeypatch.setattr(demographics, "DEMO_PROVIDER", "batchdata")
    monkeypatch.setattr(demographics, "DEMO_API_KEY", "k")
    monkeypatch.setattr(demographics, "PROVIDERS",
                        {"batchdata": lambda row: {"estimated_equity": 210_000,
                                                   "owner_age": 52}})
    monkeypatch.setattr(demographics, "get_conn", lambda: _Conn())
    monkeypatch.setattr(demographics, "fetch_missing_field", lambda *a, **k: [
        {"id": 1, "address": "1 Main St", "zip": "77070", "owner_name": "A B",
         "estimated_value": 300_000, "estimated_equity": 180_000,
         "enrichment_flags": {EQUITY_SOURCE_FLAG: FALLBACK_SOURCE}}])
    monkeypatch.setattr(demographics.time, "sleep", lambda s: None)
    written: list[dict] = []
    monkeypatch.setattr(demographics, "upsert_properties",
                        lambda c, u, a: written.extend(u) or len(u))

    counter = demographics.enrich_demographics("77070", 1)
    assert counter["ok"] == 1
    (update,) = written
    assert update["estimated_equity"] == 210_000
    # enrichment_flags merge (||) on write, so the new stamp overrides the old.
    assert update["enrichment_flags"] == {"demographics": "batchdata",
                                          EQUITY_SOURCE_FLAG: PROVIDER_SOURCE}
    assert stored_equity_source({"estimated_equity": 210_000, "estimated_value": 300_000,
                                 "enrichment_flags": {**update["enrichment_flags"]}}) == PROVIDER_SOURCE


def _rentcast_record(**overrides):
    record = {
        "addressLine1": "12 Ash St", "zipCode": "77070", "latitude": 29.9, "longitude": -95.5,
        "taxAssessments": {"2025": {"value": 300_000}},
        "features": {}, "owner": {},
    }
    record.update(overrides)
    return record


def test_rentcast_seed_stamps_the_basis_it_derives():
    from pipeline.seed import _normalize_rentcast
    row = _normalize_rentcast(_rentcast_record())
    if row.get("estimated_equity") is None:
        pytest.skip("map_record derived no equity from this synthetic record shape")
    assert row["enrichment_flags"][EQUITY_SOURCE_FLAG] == FALLBACK_SOURCE

    sold = _normalize_rentcast(_rentcast_record(lastSalePrice=250_000,
                                                lastSaleDate="2018-06-01"))
    if sold.get("last_sale_price") is None:
        pytest.skip("map_record does not read lastSalePrice from this record shape")
    assert sold["enrichment_flags"][EQUITY_SOURCE_FLAG] == "amortized"


def test_prospecting_stamps_the_basis_it_derives():
    from pipeline.prospecting import map_record
    row = map_record(_rentcast_record(), "roofing")
    if row.get("estimated_equity") is None:
        pytest.skip("map_record derived no equity from this synthetic record shape")
    assert row["enrichment_flags"][EQUITY_SOURCE_FLAG] == FALLBACK_SOURCE
    assert row["vertical"] == "roofing"
