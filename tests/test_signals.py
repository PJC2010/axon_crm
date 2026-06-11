"""Tests for pipeline/signals.py — pure timing-signal diff logic."""
from datetime import date

from pipeline.signals import baseline_for_row, events_for_row


def _row(**overrides):
    base = {
        "id": 1,
        "vertical": "roofing",
        "address": "123 Main St",
        "last_sale_date": None,
        "permit_count_24mo": None,
        "seen_sale": None,
        "seen_permits": None,
    }
    base.update(overrides)
    return base


class TestEventsForRow:
    def test_no_baseline_emits_nothing(self):
        # First run: values present but no baseline → only set the baseline.
        row = _row(last_sale_date=date(2026, 5, 1), permit_count_24mo=3)
        assert events_for_row(row) == []

    def test_newer_sale_emits_just_sold(self):
        row = _row(last_sale_date=date(2026, 5, 1), seen_sale="2019-03-12")
        events = events_for_row(row)
        assert len(events) == 1
        e = events[0]
        assert e["signal_type"] == "just_sold"
        assert e["property_id"] == 1
        assert e["vertical"] == "roofing"
        assert e["details"]["prev"] == "2019-03-12"
        assert e["details"]["new"] == "2026-05-01"

    def test_unchanged_sale_emits_nothing(self):
        row = _row(last_sale_date=date(2019, 3, 12), seen_sale="2019-03-12")
        assert events_for_row(row) == []

    def test_older_sale_emits_nothing(self):
        # Enrichment backfilling an older historical record is not a signal.
        row = _row(last_sale_date=date(2015, 1, 1), seen_sale="2019-03-12")
        assert events_for_row(row) == []

    def test_sale_cleared_emits_nothing(self):
        row = _row(last_sale_date=None, seen_sale="2019-03-12")
        assert events_for_row(row) == []

    def test_permit_increase_emits_new_permit(self):
        row = _row(permit_count_24mo=5, seen_permits="3")
        events = events_for_row(row)
        assert len(events) == 1
        assert events[0]["signal_type"] == "new_permit"
        assert events[0]["details"]["prev"] == 3
        assert events[0]["details"]["new"] == 5

    def test_permit_decrease_emits_nothing(self):
        # Counts roll off the 24-month window naturally — not a signal.
        row = _row(permit_count_24mo=1, seen_permits="3")
        assert events_for_row(row) == []

    def test_permit_zero_baseline_to_positive_emits(self):
        row = _row(permit_count_24mo=1, seen_permits="0")
        assert len(events_for_row(row)) == 1

    def test_both_signals_in_one_row(self):
        row = _row(
            last_sale_date=date(2026, 5, 1), seen_sale="2019-03-12",
            permit_count_24mo=4, seen_permits="2",
        )
        types = {e["signal_type"] for e in events_for_row(row)}
        assert types == {"just_sold", "new_permit"}

    def test_garbage_baseline_values_ignored(self):
        row = _row(
            last_sale_date=date(2026, 5, 1), seen_sale="not-a-date",
            permit_count_24mo=4, seen_permits="not-an-int",
        )
        assert events_for_row(row) == []


class TestBaselineForRow:
    def test_baseline_captures_current_values(self):
        row = _row(last_sale_date=date(2026, 5, 1), permit_count_24mo=3)
        assert baseline_for_row(row) == {
            "last_seen_sale_date": "2026-05-01",
            "last_seen_permit_count": 3,
        }

    def test_baseline_skips_missing_values(self):
        assert baseline_for_row(_row()) == {}
        assert baseline_for_row(_row(permit_count_24mo=0)) == {"last_seen_permit_count": 0}
