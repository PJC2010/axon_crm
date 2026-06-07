"""
Tests for pipeline/select.py — the pure (DB-free) selection helpers:
haversine distance, the radius predicate, and the free-field pre-score.

DB-touching orchestration (select_for_enrichment / trim_to_top_n) needs a live
Postgres, so it's covered by integration runs, not here.
"""
from datetime import date

from config import DEFAULT_WEIGHTS, EQUITY_FALLBACK_PCT
from pipeline.select import haversine_miles, prescore, _within_radius, OVERSAMPLE


# ── haversine_miles ───────────────────────────────────────────────────────────

def test_haversine_zero_distance():
    assert haversine_miles(29.76, -95.37, 29.76, -95.37) == 0.0


def test_haversine_known_distance():
    # Houston (29.7604, -95.3698) → Dallas (32.7767, -96.7970) ≈ 225 miles.
    d = haversine_miles(29.7604, -95.3698, 32.7767, -96.7970)
    assert 220 <= d <= 245


def test_haversine_one_degree_latitude():
    # One degree of latitude is ~69 miles anywhere.
    d = haversine_miles(30.0, -95.0, 31.0, -95.0)
    assert 68 <= d <= 70


# ── _within_radius ────────────────────────────────────────────────────────────

def test_within_radius_no_filter_passes_everything():
    assert _within_radius({"latitude": None, "longitude": None}, None, None) is True
    assert _within_radius({}, None, 2) is True          # center missing
    assert _within_radius({}, (29.0, -95.0), None) is True  # radius missing


def test_within_radius_inside_and_outside():
    center = (29.7604, -95.3698)
    near = {"latitude": 29.7610, "longitude": -95.3700}   # a few hundred feet
    far = {"latitude": 30.5, "longitude": -95.3698}        # ~50 miles north
    assert _within_radius(near, center, 1.0) is True
    assert _within_radius(far, center, 1.0) is False


def test_within_radius_missing_coords_excluded():
    center = (29.7604, -95.3698)
    assert _within_radius({"latitude": None, "longitude": None}, center, 5) is False
    assert _within_radius({"latitude": 29.7, "longitude": None}, center, 5) is False


# ── prescore ──────────────────────────────────────────────────────────────────

def test_prescore_uses_equity_fallback_from_value():
    """With no equity but a value present, the fallback fraction is applied so
    the equity signal contributes (matching the paid step's fallback)."""
    no_value = {"estimated_value": None, "estimated_equity": None}
    with_value = {"estimated_value": 500_000, "estimated_equity": None}
    assert prescore(with_value, DEFAULT_WEIGHTS) > prescore(no_value, DEFAULT_WEIGHTS)


def test_prescore_does_not_mutate_input_row():
    row = {"estimated_value": 200_000, "estimated_equity": None}
    prescore(row, DEFAULT_WEIGHTS)
    assert row["estimated_equity"] is None  # fallback applied on a copy only


def test_prescore_respects_existing_equity():
    """An explicit equity is used as-is; the value fallback does not override it."""
    row = {"estimated_value": 1_000_000, "estimated_equity": 50_000}
    # Fallback would be 600k (capped to target); real 50k should score lower.
    fallback_row = {"estimated_value": 1_000_000, "estimated_equity": None}
    assert prescore(row, DEFAULT_WEIGHTS) < prescore(fallback_row, DEFAULT_WEIGHTS)


def test_prescore_ranks_age_sweet_spot_higher():
    sweet = {"year_built": date.today().year - 20}   # 20yo → in sweet spot
    old = {"year_built": date.today().year - 80}      # ancient
    assert prescore(sweet, DEFAULT_WEIGHTS) > prescore(old, DEFAULT_WEIGHTS)


def test_oversample_is_above_one():
    # The over-select factor must leave slack for the post-score trim.
    assert OVERSAMPLE > 1.0
