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
        "last_storm_date": None,
        "lead_score": None,
        "score_grade": None,
        "seen_sale": None,
        "seen_permits": None,
        "seen_storm": None,
        "seen_score": None,
        "seen_grade": None,
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

    def test_newer_storm_emits_storm_event(self):
        row = _row(last_storm_date=date(2026, 5, 1), seen_storm="2024-03-01")
        events = events_for_row(row)
        assert len(events) == 1
        e = events[0]
        assert e["signal_type"] == "storm_event"
        assert e["property_id"] == 1
        assert e["details"]["prev"] == "2024-03-01"
        assert e["details"]["new"] == "2026-05-01"

    def test_no_storm_baseline_emits_nothing(self):
        row = _row(last_storm_date=date(2026, 5, 1), seen_storm=None)
        assert events_for_row(row) == []

    def test_older_storm_emits_nothing(self):
        row = _row(last_storm_date=date(2023, 1, 1), seen_storm="2024-03-01")
        assert events_for_row(row) == []

    def test_unchanged_storm_emits_nothing(self):
        row = _row(last_storm_date=date(2026, 5, 1), seen_storm="2026-05-01")
        assert events_for_row(row) == []

    def test_all_three_signals_in_one_row(self):
        row = _row(
            last_sale_date=date(2026, 5, 1), seen_sale="2019-03-12",
            permit_count_24mo=4, seen_permits="2",
            last_storm_date=date(2026, 4, 1), seen_storm="2024-01-01",
        )
        types = {e["signal_type"] for e in events_for_row(row)}
        assert types == {"just_sold", "new_permit", "storm_event"}

    def test_grade_improvement_emits_score_changed(self):
        row = _row(lead_score=88.5, score_grade="A", seen_score="62.0", seen_grade="C")
        events = events_for_row(row)
        assert len(events) == 1
        e = events[0]
        assert e["signal_type"] == "score_changed"
        assert e["property_id"] == 1
        assert e["vertical"] == "roofing"
        assert e["details"]["prev_grade"] == "C"
        assert e["details"]["new_grade"] == "A"
        assert e["details"]["prev_score"] == 62.0
        assert e["details"]["new_score"] == 88.5
        assert e["details"]["direction"] == "up"
        assert "improved" in e["details"]["summary"]
        assert "62" in e["details"]["summary"] and "88.5" in e["details"]["summary"]

    def test_grade_drop_emits_score_changed_down(self):
        row = _row(lead_score=55.0, score_grade="D", seen_score="80", seen_grade="B")
        events = events_for_row(row)
        assert len(events) == 1
        assert events[0]["signal_type"] == "score_changed"
        assert events[0]["details"]["direction"] == "down"
        assert "dropped" in events[0]["details"]["summary"]

    def test_same_grade_score_drift_emits_nothing(self):
        # 84 → 87 within band B is jitter, not a signal.
        row = _row(lead_score=87.0, score_grade="B", seen_score="84", seen_grade="B")
        assert events_for_row(row) == []

    def test_no_grade_baseline_emits_nothing(self):
        # First scored run: grade present but no baseline → only set it.
        row = _row(lead_score=88.5, score_grade="A")
        assert events_for_row(row) == []

    def test_unscored_row_emits_nothing(self):
        row = _row(seen_grade="C", seen_score="62")
        assert events_for_row(row) == []

    def test_garbage_score_baseline_ignored(self):
        row = _row(lead_score=88.5, score_grade="A", seen_score="not-a-number", seen_grade="C")
        events = events_for_row(row)
        assert len(events) == 1
        # Grade change still fires; the summary just omits the score numbers.
        assert events[0]["details"]["prev_score"] is None
        assert "score" not in events[0]["details"]["summary"]


class TestBaselineForRow:
    def test_baseline_captures_current_values(self):
        row = _row(last_sale_date=date(2026, 5, 1), permit_count_24mo=3)
        assert baseline_for_row(row) == {
            "last_seen_sale_date": "2026-05-01",
            "last_seen_permit_count": 3,
        }

    def test_baseline_captures_storm_date(self):
        row = _row(last_storm_date=date(2026, 4, 10))
        flags = baseline_for_row(row)
        assert flags.get("last_seen_storm_date") == "2026-04-10"

    def test_baseline_skips_missing_storm(self):
        row = _row()
        flags = baseline_for_row(row)
        assert "last_seen_storm_date" not in flags

    def test_baseline_skips_missing_values(self):
        assert baseline_for_row(_row()) == {}
        assert baseline_for_row(_row(permit_count_24mo=0)) == {"last_seen_permit_count": 0}

    def test_baseline_captures_score_and_grade(self):
        row = _row(lead_score=88.5, score_grade="A")
        flags = baseline_for_row(row)
        assert flags["last_seen_score_grade"] == "A"
        assert flags["last_seen_score"] == 88.5

    def test_baseline_skips_unscored_row(self):
        flags = baseline_for_row(_row())
        assert "last_seen_score_grade" not in flags
        assert "last_seen_score" not in flags
