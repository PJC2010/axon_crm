"""Tests for tools/vertical_grade_audit.py — the free-data grade audit.

The tool wraps production scoring rather than re-implementing it, so what is
worth pinning is the two claims its report rests on:

  * `free_ceiling` is the score a row that maxes every FREE signal actually
    gets from the production profile — including the gate correction, since a
    gate factor contributes no points (pipeline/scoring.py::_weighted_sum).
  * dropping the paid-only block and rescaling is a pure multiplication of the
    current score, so it re-labels grades without reordering a single lead.

Plus one smoke test that the checked-in 77396 export builds rows the way the
free pipeline leaves them (fallback equity, NULL-not-zero permit counts, no
demographic fields).
"""
import importlib.util
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import config
from pipeline import scoring
from pipeline.equity import estimate_equity
from pipeline.profiles import resolve_profile

ROOT = Path(__file__).resolve().parents[1]


def _load_tool():
    spec = importlib.util.spec_from_file_location(
        "vertical_grade_audit", ROOT / "tools" / "vertical_grade_audit.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = _load_tool()

PROPERTY_KEYS = ["default", *config.VERTICAL_WEIGHTS]
REGIONS = sorted(config.REGIONAL_CALIBRATION_MATRIX)


def _profile(vertical: str, region: str):
    return resolve_profile(None if vertical == "default" else vertical, region)


def _free_rows(profile) -> list[dict]:
    """Rows carrying only fields a free step can fill: one that saturates every
    free signal, one mid-book, one thin."""
    owner = not profile.weights.get("absentee")
    full = {
        "year_built":               date.today().year - 22,
        "last_sale_date":           date.today(),
        "estimated_equity":         1_000_000,
        "garage_spaces":            10,
        "zip_median_income":        1_000_000,
        "permit_count_24mo":        10,
        "neighborhood_value_ratio": 5.0,
        "has_pool":                 True,
        "has_cracked_slab":         True,
        "last_storm_date":          date.today(),
        "last_freeze_date":         date.today(),
        "hail_size_in":             10.0,
        "square_footage":           20_000,
        "owner_occupied":           owner,
        "ownership_years":          50,
    }
    mid = dict(full, estimated_equity=60_000, garage_spaces=1, permit_count_24mo=None,
               last_sale_date=date.today() - timedelta(days=400), square_footage=1_800,
               neighborhood_value_ratio=1.1, has_pool=None, hail_size_in=1.0)
    thin = {"year_built": date.today().year - 22, "estimated_equity": 50_000}
    return [full, mid, thin]


def test_paid_fields_are_scored_fields():
    scored = {meta["field"] for meta in config.FACTOR_META.values()}
    assert audit.PAID_FIELDS <= scored


@pytest.mark.parametrize("key", [k for k, m in config.FACTOR_META.items()
                                 if m["field"] in audit.PAID_FIELDS])
def test_paid_signal_scores_zero_when_absent(key):
    # The premise of "constant zero": an un-appended row scores nothing on it.
    assert scoring._SIGNAL_FNS[key](None) == 0.0


@pytest.mark.parametrize("region", REGIONS)
@pytest.mark.parametrize("vertical", PROPERTY_KEYS)
def test_free_ceiling_is_what_a_perfect_free_row_scores(vertical, region):
    profile = _profile(vertical, region)
    dead, live, ceiling = audit.free_ceiling(profile)
    assert 0.0 <= dead < live <= 1.0
    perfect_free = _free_rows(profile)[0]
    assert scoring.compute_score(perfect_free, profile) == pytest.approx(ceiling, abs=1.0)


def test_free_ceiling_reads_the_gate():
    # pool_maintenance gates on `pool`; that weight never contributes points, so
    # the paid share must be read against the live (non-gate) weight.
    profile = _profile("pool_maintenance", "us")
    dead, live, ceiling = audit.free_ceiling(profile)
    gate = profile.weights["pool"]
    assert live == pytest.approx(1.0 - gate)
    assert ceiling == pytest.approx(100 * (live - dead) / live)
    assert ceiling < 100 * (1 - dead)


@pytest.mark.parametrize("region", REGIONS)
@pytest.mark.parametrize("vertical", PROPERTY_KEYS)
def test_drop_paid_is_a_pure_rescale(vertical, region):
    profile = _profile(vertical, region)
    profile_key = vertical if vertical in config.VERTICAL_WEIGHTS else "default"
    variants = dict(audit.build_variants(profile, region, profile_key, {}))
    dead, live, _ceiling = audit.free_ceiling(profile)
    if "drop_paid" not in variants:
        assert dead == 0.0
        return
    scale = live / (live - dead)
    for row in _free_rows(profile):
        current = scoring.compute_score(row, variants["current"])
        dropped = scoring.compute_score(row, variants["drop_paid"])
        # Weights are rounded to 4 places by apply_weight_spec — allow that.
        assert dropped == pytest.approx(current * scale, abs=0.1)


def test_proposal_is_applied_through_the_regional_delta_machinery():
    profile = _profile("roofing", "tx_houston")
    variants = dict(audit.build_variants(
        profile, "tx_houston", "roofing", {},
        proposal={"scale": {"permit": 0.5, "home_improvement": 0.0}, "set": {"home_size": 0.06}}))
    weights = variants["proposal"].weights
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-6)
    assert weights["home_size"] == pytest.approx(0.06)
    assert weights["home_improvement"] == 0.0
    assert weights["permit"] < profile.weights["permit"]


def test_export_rows_mirror_the_free_pipeline():
    args = SimpleNamespace(income=76_500, garage=None, pool_share=None, storm_months=None,
                           hail_in=None, freeze_months=None, all_parcels=False)
    rows, meta = audit.build_rows("77396", date(2026, 9, 5), args)
    assert meta["scored"] > 10_000
    first = rows[0]
    # Texas is non-disclosure: no sale price, so equity is the flat fallback
    # exactly as pipeline/hcad_enrichment.py stores it.
    assert first["estimated_equity"] == estimate_equity(
        first["estimated_value"], last_sale_date=first["last_sale_date"])
    # A parcel with no permit in the window stays NULL, never 0.
    assert all(r["permit_count_24mo"] is None or r["permit_count_24mo"] >= 1 for r in rows)
    assert any(r["permit_count_24mo"] for r in rows)
    # Nothing a paid step writes is present.
    assert all(r.get(field) is None for r in rows for field in audit.PAID_FIELDS)
    # Every row carries the fields the free signals read.
    for field in ("year_built", "square_footage", "estimated_value", "owner_occupied",
                  "neighborhood_value_ratio", "zip_median_income"):
        assert all(r[field] is not None for r in rows), field
