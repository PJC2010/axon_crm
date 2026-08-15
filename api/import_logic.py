"""
Pure (no-DB) helpers for the contact / lead CSV import.

Kept free of database and FastAPI concerns so the column auto-detection and row
normalization can be unit-tested directly (same style as pipeline/scoring.py).
The route in api/routes/imports.py wires these into UploadFile parsing and the
properties upsert.
"""
from __future__ import annotations

import re

# Real properties columns an imported row may populate.
TARGET_FIELDS = [
    "contact_name", "contact_phone", "contact_email", "owner_name",
    "address", "city", "state", "zip",
    "estimated_value", "vertical", "status",
]

# Internal tokens that don't map 1:1 to a column — recombined in normalize_row.
_FIRST = "__first__"
_LAST = "__last__"
_ADDR_FORMATTED = "__addr_formatted__"


def _key(header: str) -> str:
    """Normalize a header for fuzzy matching: lowercase, strip, collapse
    non-alphanumerics to single spaces."""
    return re.sub(r"[^a-z0-9]+", " ", (header or "").lower()).strip()


# Google Contacts export (both the classic and the current "Google CSV" layouts).
GOOGLE_CONTACTS_ALIASES = {
    "name": "contact_name",
    "given name": _FIRST,
    "first name": _FIRST,
    "family name": _LAST,
    "last name": _LAST,
    "e mail 1 value": "contact_email",
    "email 1 value": "contact_email",
    "phone 1 value": "contact_phone",
    "organization 1 name": "owner_name",
    "organization name": "owner_name",
    "address 1 formatted": _ADDR_FORMATTED,
    "address 1 street": "address",
    "address 1 city": "city",
    "address 1 region": "state",
    "address 1 postal code": "zip",
}

# Generic spreadsheet headers.
GENERIC_ALIASES = {
    "name": "contact_name",
    "full name": "contact_name",
    "contact": "contact_name",
    "contact name": "contact_name",
    "first name": _FIRST,
    "last name": _LAST,
    "phone": "contact_phone",
    "phone number": "contact_phone",
    "mobile": "contact_phone",
    "cell": "contact_phone",
    "telephone": "contact_phone",
    "email": "contact_email",
    "email address": "contact_email",
    "e mail": "contact_email",
    "e mail address": "contact_email",
    "owner": "owner_name",
    "owner name": "owner_name",
    "address": "address",
    "street": "address",
    "street address": "address",
    "address line 1": "address",
    "city": "city",
    "state": "state",
    "region": "state",
    "province": "state",
    "zip": "zip",
    "zip code": "zip",
    "postal code": "zip",
    "postcode": "zip",
    "estimated value": "estimated_value",
    "value": "estimated_value",
    "deal value": "estimated_value",
    "vertical": "vertical",
    "service": "vertical",
    "trade": "vertical",
    "status": "status",
    "stage": "status",
}


def detect_mapping(headers: list[str]) -> dict[str, str]:
    """Best-effort map of original CSV header -> target field (or internal token).

    Google Contacts aliases take precedence (they're more specific), then generic.
    Headers we don't recognize are simply left out of the mapping.
    """
    mapping: dict[str, str] = {}
    for header in headers:
        if header is None:
            continue
        key = _key(header)
        target = GOOGLE_CONTACTS_ALIASES.get(key) or GENERIC_ALIASES.get(key)
        if target:
            mapping[header] = target
    return mapping


# Control characters (including NUL) can't be stored in a Postgres text column
# at all — psycopg2 raises before the INSERT is even sent — so a single stray
# byte from a mangled export would fail the row outright. Strip them instead.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Thousands-grouped integers: 1,234 / 1.234.567. Used to tell a grouping
# separator from a decimal point when only one kind of separator is present.
_GROUPED = re.compile(r"^\d{1,3}([,.]\d{3})+$")
_NUMERIC = re.compile(r"^\d+(\.\d+)?$")
# Spreadsheet shorthand: 15k, 1.2M.
_SUFFIXES = {"k": 1_000, "m": 1_000_000}


def clean_value(value: str) -> str:
    """Strip control characters and surrounding whitespace from a CSV cell."""
    return _CONTROL.sub("", value or "").strip()


def parse_amount(value: str) -> int | None:
    """Parse a spreadsheet money cell into whole currency units.

    Handles the shapes a real export actually contains — "$15,000", "15000.00",
    "1,500.50", "(200)" for a negative, "15k" — and returns None for anything
    that isn't a number, so an unparseable cell is dropped rather than turned
    into a bogus figure. The naive "keep the digits" approach this replaces read
    "1,500.50" as 150050, a 100x overstatement that then fed scoring.

    Negative amounts are rejected too: estimated_value is a property value / deal
    size, so a negative is bad data, not a small number.
    """
    text = clean_value(value).lower()
    if not text:
        return None

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1].strip()
    text = re.sub(r"^[^\d(.-]+", "", text).strip()      # currency symbol/prefix
    if text.startswith("-"):
        negative, text = True, text[1:].strip()

    multiplier = 1
    if text and text[-1] in _SUFFIXES:
        multiplier, text = _SUFFIXES[text[-1]], text[:-1].strip()

    text = re.sub(r"[\s ]", "", text)
    if not text:
        return None

    if "," in text and "." in text:
        # The rightmost separator is the decimal point; the other groups digits.
        dec = "," if text.rfind(",") > text.rfind(".") else "."
        text = text.replace("." if dec == "," else ",", "").replace(dec, ".")
    elif _GROUPED.match(text):
        text = text.replace(",", "").replace(".", "")
    elif "," in text:
        text = text.replace(",", ".")                    # 1500,50 -> 1500.50

    if not _NUMERIC.match(text):
        return None
    amount = round(float(text) * multiplier)
    return None if negative or amount < 0 else amount


def normalize_status(value: str) -> str:
    """Fold a status cell onto the key form the pipeline stores.

    "Quote Sent" / "quote-sent" / " WON " all name real stages; without this
    they land in properties.status verbatim and the lead then belongs to no
    Kanban column at all. Validating the result against the account's stages is
    the route's job — this only fixes the shape.
    """
    return re.sub(r"[^a-z0-9]+", "_", clean_value(value).lower()).strip("_")


def normalize_zip(value: str) -> str:
    """Reduce a US ZIP+4 to its 5-digit form, leaving anything else alone.

    zip is part of the property uniqueness key and every ZIP-scoped query and
    pipeline run matches on the 5-digit form, so "77002-1234" would both
    duplicate the lead and hide it from its own ZIP.
    """
    text = clean_value(value)
    m = re.match(r"^(\d{5})[-\s]?\d{4}$", text)
    return m.group(1) if m else text


def normalize_row(raw: dict, mapping: dict[str, str]) -> dict:
    """Apply a header->field mapping to one CSV row and clean the values.

    Combines first/last name into contact_name, falls back to a formatted
    address when no street column is mapped, lowercases email, folds status and
    zip onto their canonical forms, and parses estimated_value. Empty values are
    dropped so they never clobber existing data on upsert.
    """
    out: dict = {}
    first = last = formatted = None

    for header, target in mapping.items():
        val = clean_value(raw.get(header) or "")
        if not val:
            continue
        if target == _FIRST:
            first = val
        elif target == _LAST:
            last = val
        elif target == _ADDR_FORMATTED:
            formatted = val
        elif target in TARGET_FIELDS and target not in out:
            out[target] = val

    if "contact_name" not in out:
        name = " ".join(p for p in (first, last) if p).strip()
        if name:
            out["contact_name"] = name

    if "address" not in out and formatted:
        out["address"] = formatted

    if "contact_email" in out:
        out["contact_email"] = out["contact_email"].lower()

    if "zip" in out:
        out["zip"] = normalize_zip(out["zip"])

    if "status" in out:
        status = normalize_status(out["status"])
        if status:
            out["status"] = status
        else:
            del out["status"]

    if "estimated_value" in out:
        parsed = parse_amount(out["estimated_value"])
        if parsed is None:
            del out["estimated_value"]
        else:
            out["estimated_value"] = parsed

    return out


def row_is_usable(row: dict) -> bool:
    """A row is worth importing if it has an address or any contact identifier."""
    return any(row.get(f) for f in
               ("address", "contact_email", "contact_phone", "contact_name", "owner_name"))
