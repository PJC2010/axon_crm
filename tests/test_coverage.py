"""Tests for pipeline/coverage.py — pure fill-rate math (no DB)."""
from pipeline.coverage import compute_fill_rates, rates_from_counts


def test_empty_rows_gives_zero_pct():
    rates = compute_fill_rates([], fields=["owner_name"])
    assert rates["owner_name"] == {"filled": 0, "total": 0, "pct": 0.0}


def test_counts_non_null_only():
    rows = [
        {"owner_name": "A", "contact_phone": None},
        {"owner_name": "B", "contact_phone": "555"},
        {"owner_name": None, "contact_phone": None},
    ]
    rates = compute_fill_rates(rows, fields=["owner_name", "contact_phone"])
    assert rates["owner_name"] == {"filled": 2, "total": 3, "pct": 66.7}
    assert rates["contact_phone"] == {"filled": 1, "total": 3, "pct": 33.3}


def test_missing_key_treated_as_null():
    rows = [{"owner_name": "A"}, {}]   # second row lacks the key entirely
    rates = compute_fill_rates(rows, fields=["owner_name"])
    assert rates["owner_name"]["filled"] == 1


def test_full_coverage_is_100pct():
    rows = [{"x": 1}, {"x": 2}]
    assert compute_fill_rates(rows, fields=["x"])["x"]["pct"] == 100.0


# ── rates_from_counts ─────────────────────────────────────────────────────────
# The SQL-aggregated path used by the account-wide audit. It must produce the
# same shape as compute_fill_rates, since both feed the same report.

def test_counts_produce_the_same_shape_as_row_counting():
    rows = [
        {"owner_name": "A", "contact_phone": None},
        {"owner_name": "B", "contact_phone": "555"},
        {"owner_name": None, "contact_phone": None},
    ]
    from_rows = compute_fill_rates(rows, fields=["owner_name", "contact_phone"])
    # What "SELECT COUNT(owner_name), COUNT(contact_phone)" would return.
    from_counts = rates_from_counts(3, {"owner_name": 2, "contact_phone": 1})
    assert from_counts == from_rows


def test_empty_account_reports_zero_not_a_division_error():
    assert rates_from_counts(0, {"owner_name": 0}) == {
        "owner_name": {"filled": 0, "total": 0, "pct": 0.0},
    }


def test_full_coverage_from_counts_is_100pct():
    assert rates_from_counts(8, {"x": 8})["x"]["pct"] == 100.0
