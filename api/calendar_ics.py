"""
Pure (no-DB, no-network) iCalendar (.ics) generation for appointment invites.

Kept free of FastAPI/DB concerns so the formatting can be unit-tested directly
(same style as pipeline/scoring.py and api/import_logic.py). The appointments
route wires this into email delivery via api/notifications.py.
"""
from __future__ import annotations

from datetime import datetime, timezone

PRODID = "-//Axon CRM//Appointments//EN"


def _fmt_dt(dt: datetime) -> str:
    """Format a datetime as a UTC iCalendar timestamp (YYYYMMDDTHHMMSSZ).

    Naive datetimes are assumed to already be UTC; aware ones are converted.
    """
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _escape(text: str | None) -> str:
    """Escape text per RFC 5545: backslash, semicolon, comma, and newlines."""
    if not text:
        return ""
    return (
        text.replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace("\r\n", "\\n")
            .replace("\n", "\\n")
    )


def build_ics(
    *,
    uid: str,
    summary: str,
    start: datetime,
    end: datetime,
    location: str | None = None,
    description: str | None = None,
    organizer_email: str | None = None,
    dtstamp: datetime | None = None,
) -> str:
    """Build a single-event VCALENDAR string (CRLF-terminated lines)."""
    stamp = dtstamp or datetime.now(timezone.utc)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_fmt_dt(stamp)}",
        f"DTSTART:{_fmt_dt(start)}",
        f"DTEND:{_fmt_dt(end)}",
        f"SUMMARY:{_escape(summary)}",
    ]
    if location:
        lines.append(f"LOCATION:{_escape(location)}")
    if description:
        lines.append(f"DESCRIPTION:{_escape(description)}")
    if organizer_email:
        lines.append(f"ORGANIZER:mailto:{organizer_email}")
    lines += ["STATUS:CONFIRMED", "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"
