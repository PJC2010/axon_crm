"""
Pure (no-DB) building blocks for digital-presence connectors.

Each provider parser (e.g. api/connectors/meta.py) turns an uploaded export into a
``ParsedSocial`` of normalized metric/post dicts. Kept free of database and FastAPI
concerns so parsing can be unit-tested directly (same style as api/import_logic.py).
The route in api/routes/connections.py wires these into UploadFile parsing and the
social_metrics / social_posts upserts.

A "metric" dict targets the social_metrics columns; a "post" dict targets the
social_posts columns. Empty/None values are dropped so they never clobber existing
data on upsert.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class ParsedSocial:
    """The normalized result of parsing one export file."""
    metrics: list[dict] = field(default_factory=list)   # -> social_metrics rows
    posts: list[dict] = field(default_factory=list)     # -> social_posts rows
    export_kind: str | None = None                      # business_suite_csv | ads_manager_csv | dyi_json
    period_start: date | None = None
    period_end: date | None = None
    errors: list[str] = field(default_factory=list)

    def extend(self, other: "ParsedSocial") -> None:
        """Merge another ParsedSocial into this one (used when a file yields both)."""
        self.metrics.extend(other.metrics)
        self.posts.extend(other.posts)
        self.errors.extend(other.errors)
        self.export_kind = self.export_kind or other.export_kind

    def finalize(self) -> "ParsedSocial":
        """Compute the observed date window from the parsed rows."""
        dates: list[date] = []
        for m in self.metrics:
            d = m.get("metric_date")
            if isinstance(d, date):
                dates.append(d)
        for p in self.posts:
            ts = p.get("posted_at")
            if isinstance(ts, datetime):
                dates.append(ts.date())
        if dates:
            self.period_start = min(dates)
            self.period_end = max(dates)
        return self


def key(header: str) -> str:
    """Normalize a header for fuzzy matching: lowercase, strip, collapse
    non-alphanumerics to single spaces (mirrors api.import_logic._key)."""
    return re.sub(r"[^a-z0-9]+", " ", (header or "").lower()).strip()


def parse_int(value) -> int | None:
    """Best-effort integer from a string like '1,234' or '12.0'."""
    if value is None:
        return None
    if isinstance(value, (int,)):
        return int(value)
    if isinstance(value, float):
        return int(value)
    s = str(value).strip()
    if not s:
        return None
    # Drop thousands separators / currency, keep a leading sign and digits.
    s = re.sub(r"[,$%\s]", "", s)
    m = re.match(r"-?\d+", s)
    return int(m.group(0)) if m else None


def parse_money(value) -> float | None:
    """Best-effort decimal from a string like '$1,234.56' or '2.0x'."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    s = re.sub(r"[,$%\sx]", "", s, flags=re.IGNORECASE)
    m = re.match(r"-?\d+(\.\d+)?", s)
    return float(m.group(0)) if m else None


# Date formats seen across Meta exports (Business Suite, Ads Manager, DYI).
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d/%m/%Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
)


def parse_date(value) -> date | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # Unix epoch seconds (DYI JSON timestamps).
    if s.isdigit() and len(s) >= 9:
        try:
            return datetime.utcfromtimestamp(int(s)).date()
        except (ValueError, OverflowError):
            pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s[: len(fmt) + 4], fmt).date()
        except ValueError:
            continue
    # Last resort: ISO prefix YYYY-MM-DD.
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def parse_datetime(value) -> datetime | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.isdigit() and len(s) >= 9:
        try:
            return datetime.utcfromtimestamp(int(s))
        except (ValueError, OverflowError):
            pass
    # Normalize the ISO 'T' separator and drop any trailing timezone/fraction.
    s2 = re.sub(r"[+Z].*$", "", s.replace("T", " ")).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M:%S",
                "%m/%d/%Y %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s2, fmt)
        except ValueError:
            continue
    d = parse_date(s)
    return datetime(d.year, d.month, d.day) if d else None


# Map raw "post type" / "media type" strings to our normalized content_type values.
_CONTENT_TYPE_ALIASES = {
    "photo": "photo",
    "image": "photo",
    "video": "video",
    "reel": "reel",
    "reels": "reel",
    "carousel": "carousel",
    "carousel album": "carousel",
    "album": "carousel",
    "status": "text",
    "text": "text",
    "story": "story",
    "stories": "story",
    "link": "link",
    "shared link": "link",
}


def classify_content_type(value: str | None) -> str | None:
    if not value:
        return None
    return _CONTENT_TYPE_ALIASES.get(key(value), key(value) or None)


def first(row: dict, aliases: dict, target_key: str):
    """Return the value of the first header in `row` whose normalized key maps to
    `target_key` in `aliases`. Lets a parser pull a logical field regardless of the
    exact (or localized) column label the export used."""
    for header, val in row.items():
        if aliases.get(key(header)) == target_key and str(val).strip():
            return val
    return None
