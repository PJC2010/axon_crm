"""Tests for the public ZIP-sample teaser helpers (api/zip_sample_logic.py):
masking must never leak a full house number, value labels stay deliberately
imprecise, and a freshly seeded ZIP still shows its best leads."""
import re

from api.zip_sample_logic import mask_address, teaser_rank_key, value_label


def test_mask_keeps_street_hides_house_number():
    assert mask_address("1842 Westheimer Rd") == "18XX Westheimer Rd"
    assert mask_address("504 River Oaks Blvd") == "5XX River Oaks Blvd"
    assert mask_address("77 Tanglewood Ln") == "7X Tanglewood Ln"


def test_mask_always_hides_at_least_one_digit():
    # Whatever the house-number length, the exact parcel must not be recoverable.
    for n in ("7", "42", "319", "12345", "180765"):
        masked = mask_address(f"{n} Main St")
        leading = masked.split()[0]
        assert "X" in leading, masked
        assert leading != n


def test_mask_handles_odd_shapes():
    assert mask_address("") == ""
    assert mask_address(None) == ""
    # No leading house number: every digit run is masked instead.
    assert mask_address("Corner of Elm & 5th") == "Corner of Elm & Xth"
    # Digit-free descriptions pass through (nothing identifying to hide).
    assert mask_address("Oak Meadow Estate") == "Oak Meadow Estate"


def test_value_label_rounds_and_degrades():
    assert value_label(483_250) == "~$485K"
    assert value_label(1_240_000) == "~$1.2M"
    assert value_label(2_000_000) == "~$2M"
    assert value_label(None) == ""
    assert value_label("not-a-number") == ""
    assert value_label(0) == ""
    # Never emits enough precision to identify the parcel's exact county value.
    assert not re.search(r"\d{6}", value_label(487_631))


# ── Teaser ranking ────────────────────────────────────────────────────────────

def _sorted(pairs):
    """Rank (row, score) pairs the way the endpoint does, best first."""
    return [row["id"] for row, _ in
            sorted(pairs, key=lambda t: teaser_rank_key(t[0], t[1]), reverse=True)]


def test_benchmarked_rows_keep_their_score_order():
    rows = [({"id": 1, "neighborhood_value_pctile": 0.2}, 55.0),
            ({"id": 2, "neighborhood_value_pctile": 0.9}, 81.0),
            ({"id": 3, "neighborhood_value_pctile": 0.5}, 67.0)]
    assert _sorted(rows) == [2, 3, 1]


def test_unbenchmarked_rows_fall_back_to_lead_score():
    # A freshly seeded ZIP has no benchmark yet; without the fallback every row
    # ranks as if it sat at its block median and the teaser looks empty.
    rows = [({"id": 1, "neighborhood_value_pctile": None, "lead_score": 40}, 0.0),
            ({"id": 2, "neighborhood_value_pctile": None, "lead_score": 91}, 0.0),
            ({"id": 3, "neighborhood_value_pctile": None, "lead_score": 66}, 0.0)]
    assert _sorted(rows) == [2, 3, 1]


def test_benchmarked_rows_outrank_unbenchmarked_ones():
    rows = [({"id": 1, "neighborhood_value_pctile": None, "lead_score": 99}, 99.0),
            ({"id": 2, "neighborhood_value_pctile": 0.1}, 12.0)]
    assert _sorted(rows) == [2, 1]


def test_missing_lead_score_sorts_last_without_raising():
    rows = [({"id": 1, "neighborhood_value_pctile": None}, 0.0),
            ({"id": 2, "neighborhood_value_pctile": None, "lead_score": None}, 0.0),
            ({"id": 3, "neighborhood_value_pctile": None, "lead_score": "x"}, 0.0),
            ({"id": 4, "neighborhood_value_pctile": None, "lead_score": 5}, 0.0)]
    assert _sorted(rows)[0] == 4


def test_ranking_invents_no_benchmark():
    # Presentation fallback only — the fallback tier never borrows a percentile.
    row = {"id": 1, "neighborhood_value_pctile": None, "lead_score": 80}
    teaser_rank_key(row, 80.0)
    assert row["neighborhood_value_pctile"] is None
