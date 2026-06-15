"""Tests for api/calendar_ics.py — pure iCalendar generation (no DB/network)."""
from datetime import datetime, timezone, timedelta

from api.calendar_ics import build_ics, _fmt_dt, _escape


# ── _fmt_dt ───────────────────────────────────────────────────────────────────

class TestFmtDt:
    def test_naive_treated_as_utc(self):
        assert _fmt_dt(datetime(2026, 6, 15, 15, 30, 0)) == "20260615T153000Z"

    def test_aware_utc(self):
        assert _fmt_dt(datetime(2026, 6, 15, 15, 30, 0, tzinfo=timezone.utc)) == "20260615T153000Z"

    def test_aware_offset_converted_to_utc(self):
        # 10:30 at UTC-5 is 15:30 UTC.
        dt = datetime(2026, 6, 15, 10, 30, 0, tzinfo=timezone(timedelta(hours=-5)))
        assert _fmt_dt(dt) == "20260615T153000Z"


# ── _escape ───────────────────────────────────────────────────────────────────

class TestEscape:
    def test_none_and_empty(self):
        assert _escape(None) == ""
        assert _escape("") == ""

    def test_special_chars(self):
        assert _escape("a,b;c\\d") == "a\\,b\\;c\\\\d"

    def test_newlines(self):
        assert _escape("line1\nline2") == "line1\\nline2"
        assert _escape("line1\r\nline2") == "line1\\nline2"


# ── build_ics ─────────────────────────────────────────────────────────────────

class TestBuildIcs:
    def _ics(self, **overrides):
        kwargs = dict(
            uid="appt-1@axon-crm",
            summary="Roof inspection",
            start=datetime(2026, 6, 15, 15, 0, 0, tzinfo=timezone.utc),
            end=datetime(2026, 6, 15, 16, 0, 0, tzinfo=timezone.utc),
            dtstamp=datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        )
        kwargs.update(overrides)
        return build_ics(**kwargs)

    def test_wraps_in_vcalendar_and_vevent(self):
        ics = self._ics()
        assert ics.startswith("BEGIN:VCALENDAR\r\n")
        assert ics.rstrip().endswith("END:VCALENDAR")
        assert "BEGIN:VEVENT" in ics and "END:VEVENT" in ics

    def test_crlf_line_endings(self):
        # RFC 5545 requires CRLF; ensure no bare LF without a preceding CR.
        ics = self._ics()
        assert "\r\n" in ics
        assert "\n" not in ics.replace("\r\n", "")

    def test_includes_core_fields(self):
        ics = self._ics()
        assert "UID:appt-1@axon-crm" in ics
        assert "SUMMARY:Roof inspection" in ics
        assert "DTSTART:20260615T150000Z" in ics
        assert "DTEND:20260615T160000Z" in ics
        assert "DTSTAMP:20260601T120000Z" in ics

    def test_optional_fields_omitted_when_absent(self):
        ics = self._ics()
        assert "LOCATION:" not in ics
        assert "DESCRIPTION:" not in ics
        assert "ORGANIZER:" not in ics

    def test_optional_fields_present_and_escaped(self):
        ics = self._ics(location="123 Main St, Houston", description="Bring ladder; check vents",
                        organizer_email="rep@example.com")
        assert "LOCATION:123 Main St\\, Houston" in ics
        assert "DESCRIPTION:Bring ladder\\; check vents" in ics
        assert "ORGANIZER:mailto:rep@example.com" in ics
