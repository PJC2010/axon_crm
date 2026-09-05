"""score_zip keeps every row on the vertical it was last scored with.

The two account-wide rescores (POST /pipeline/rescore-all and the post-backfill
rescore in api/scheduler.py) call score_zip with vertical=None. Before
rows_by_vertical, None meant "default profile for every row", which silently
moved a roofing book onto the generic weights (+14 to +28 points on the same
Houston row) while the stored `vertical` column kept saying "roofing" because
the upsert never writes a None. These tests pin the rule: None preserves each
row's own vertical; an explicit vertical re-labels the whole ZIP.
"""
from datetime import date

import pytest

import pipeline.scorer as scorer
from pipeline import regional
from pipeline.equity import EQUITY_SOURCE_FLAG
from pipeline.profiles import resolve_profile
from pipeline.scoring import compute_score


ZIP = "77070"   # Houston → tx_houston calibration


class _Conn:
    def close(self):
        pass

    def rollback(self):
        pass


def _row(id, vertical, **overrides):
    row = {
        "id": id, "address": f"{id} Pin Oak Forest Dr", "zip": ZIP, "state": "TX",
        "vertical": vertical,
        "year_built": 2001, "estimated_value": 320_000, "estimated_equity": None,
        "last_sale_price": None, "last_sale_date": date(2025, 11, 1),
        "garage_spaces": 2, "zip_median_income": 78_000, "permit_count_24mo": 1,
        "neighborhood_value_ratio": 1.1, "square_footage": 2_300,
        "owner_occupied": True, "enrichment_flags": {},
    }
    row.update(overrides)
    return row


@pytest.fixture
def run(monkeypatch):
    """score_zip with every side effect stubbed; returns the captured updates."""
    captured: list[dict] = []

    def _run(rows, vertical):
        captured.clear()
        monkeypatch.setattr(scorer, "get_conn", lambda: _Conn())
        monkeypatch.setattr(scorer, "fetch_by_zip", lambda c, z, a: rows)
        monkeypatch.setattr(scorer, "upsert_properties",
                            lambda c, u, a: captured.extend(u) or len(u))
        monkeypatch.setattr(scorer, "write_score_snapshots", lambda *a, **k: None)
        monkeypatch.setattr(scorer, "_apply_ml", lambda *a, **k: None)
        monkeypatch.setattr("pipeline.focus.recompute_focus", lambda *a, **k: None)
        n = scorer.score_zip(ZIP, 1, vertical=vertical)
        assert n == len(rows)
        return {u["address"]: u for u in captured}
    return _run


# ── rows_by_vertical (pure) ───────────────────────────────────────────────────

def test_none_groups_rows_by_their_stored_vertical():
    rows = [_row(1, "roofing"), _row(2, None), _row(3, "roofing"), _row(4, "hvac")]
    groups = scorer.rows_by_vertical(rows, None)
    assert {k: [r["id"] for r in v] for k, v in groups.items()} == {
        "roofing": [1, 3], None: [2], "hvac": [4]}


def test_explicit_vertical_relabels_every_row():
    rows = [_row(1, "roofing"), _row(2, None)]
    groups = scorer.rows_by_vertical(rows, "hvac")
    assert list(groups) == ["hvac"] and [r["id"] for r in groups["hvac"]] == [1, 2]


def test_empty_string_vertical_is_treated_as_unset():
    # A row seeded by a path that wrote '' rather than NULL must not become
    # its own profile key — resolve_profile('') is the default anyway, and the
    # group label must say so.
    groups = scorer.rows_by_vertical([_row(1, "")], None)
    assert list(groups) == [None]


# ── score_zip with vertical=None ──────────────────────────────────────────────

def test_rescore_without_vertical_keeps_each_rows_profile(run):
    rows = [_row(1, "roofing"), _row(2, None)]
    updates = run(rows, None)
    region = regional.resolve_region(ZIP, "TX")

    roofing = updates[rows[0]["address"]]
    assert roofing["vertical"] == "roofing"
    assert roofing["enrichment_flags"]["scored"] == "roofing"
    expected = compute_score(rows[0], resolve_profile("roofing", region))
    assert roofing["lead_score"] == round(expected, 2)

    plain = updates[rows[1]["address"]]
    assert plain["vertical"] is None          # upsert never writes a None
    assert plain["enrichment_flags"]["scored"] == "default"
    assert plain["lead_score"] == round(
        compute_score(rows[1], resolve_profile(None, region)), 2)

    # The whole point: the same inputs score very differently on the two
    # profiles, so a rescore that dropped the vertical would have moved the
    # roofing lead by tens of points.
    assert abs(roofing["lead_score"] - plain["lead_score"]) > 10


def test_explicit_vertical_relabels_and_rescores_every_row(run):
    rows = [_row(1, "roofing"), _row(2, None)]
    updates = run(rows, "hvac")
    region = regional.resolve_region(ZIP, "TX")
    hvac = resolve_profile("hvac", region)
    for row in rows:
        u = updates[row["address"]]
        assert u["vertical"] == "hvac"
        assert u["enrichment_flags"]["scored"] == "hvac"
        assert u["lead_score"] == round(compute_score(row, hvac), 2)


def test_rescore_is_idempotent_for_a_vertical_book(run):
    """Scoring a row, then rescoring it with vertical=None from the state the
    first pass persisted, must reproduce the first score exactly. This is the
    rescore-all / backfill path, and it used to move every vertical row."""
    first = run([_row(1, "roofing")], "roofing")[_row(1, "roofing")["address"]]
    persisted = _row(1, "roofing",
                     estimated_equity=first["estimated_equity"],
                     enrichment_flags=first["enrichment_flags"])
    second = run([persisted], None)[persisted["address"]]
    assert second["lead_score"] == first["lead_score"]
    assert second["score_grade"] == first["score_grade"]
    assert second["vertical"] == "roofing"


# ── equity provenance persisted by the scorer ─────────────────────────────────

def test_scorer_backfill_stamps_fallback_provenance(run):
    row = _row(1, None)                         # estimated_equity None, no sale price
    u = run([row], None)[row["address"]]
    assert u["estimated_equity"] == int(320_000 * 0.6)
    assert u["enrichment_flags"][EQUITY_SOURCE_FLAG] == "fallback"


def test_scorer_does_not_restamp_an_already_stamped_row(run):
    row = _row(1, None, estimated_equity=192_000,
               enrichment_flags={EQUITY_SOURCE_FLAG: "fallback"})
    u = run([row], None)[row["address"]]
    assert EQUITY_SOURCE_FLAG not in u["enrichment_flags"]


def test_scorer_stamps_a_legacy_fallback_row_by_rederivation(run):
    # Written before the stamp existed: equity equals value × pct exactly.
    row = _row(1, None, estimated_equity=192_000, enrichment_flags={})
    u = run([row], None)[row["address"]]
    assert u["enrichment_flags"][EQUITY_SOURCE_FLAG] == "fallback"


def test_persisted_fallback_stamp_haircuts_even_when_value_moved(run):
    # Value refreshed after the fallback was written: the number no longer
    # equals value × pct, so re-derivation would say "unknown" — the stamp is
    # what keeps the haircut on the number that is still the flat proxy.
    stamped = _row(1, None, estimated_value=400_000, estimated_equity=192_000,
                   enrichment_flags={EQUITY_SOURCE_FLAG: "fallback"})
    unstamped = _row(2, None, estimated_value=400_000, estimated_equity=192_000,
                     enrichment_flags={})
    updates = run([stamped, unstamped], None)
    assert (updates[stamped["address"]]["lead_score"]
            < updates[unstamped["address"]]["lead_score"])


def test_measured_stamp_beats_a_coincidental_fallback_number(run):
    measured = _row(1, None, estimated_equity=192_000,        # == 320k × 0.6
                    enrichment_flags={EQUITY_SOURCE_FLAG: "balance"})
    fallback = _row(2, None, estimated_equity=192_000, enrichment_flags={})
    updates = run([measured, fallback], None)
    assert (updates[measured["address"]]["lead_score"]
            > updates[fallback["address"]]["lead_score"])
    assert EQUITY_SOURCE_FLAG not in updates[measured["address"]]["enrichment_flags"]


def test_non_property_profile_key_in_stored_vertical_scores_on_default(run):
    # The registry also holds roll-up profiles; a property row must never be
    # scored on one just because its free-text vertical happens to match.
    rows = [_row(1, "retail_rfm"), _row(2, None)]
    updates = run(rows, None)
    assert updates[rows[0]["address"]]["vertical"] == "retail_rfm"
    assert updates[rows[0]["address"]]["enrichment_flags"]["scored"] == "default"
    assert (updates[rows[0]["address"]]["lead_score"]
            == updates[rows[1]["address"]]["lead_score"])


def test_scorer_leaves_unattributable_equity_unstamped(run):
    row = _row(1, None, estimated_equity=150_000, enrichment_flags={})
    u = run([row], None)[row["address"]]
    assert EQUITY_SOURCE_FLAG not in u["enrichment_flags"]
