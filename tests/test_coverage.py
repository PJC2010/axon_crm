"""Tests for pipeline/coverage.py — pure fill-rate math (no DB)."""
from pipeline.coverage import compute_fill_rates


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
