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


def _parse_int(value: str) -> int | None:
    digits = re.sub(r"[^0-9]", "", value or "")
    return int(digits) if digits else None


def normalize_row(raw: dict, mapping: dict[str, str]) -> dict:
    """Apply a header->field mapping to one CSV row and clean the values.

    Combines first/last name into contact_name, falls back to a formatted
    address when no street column is mapped, lowercases email, and parses
    estimated_value. Empty values are dropped so they never clobber existing
    data on upsert.
    """
    out: dict = {}
    first = last = formatted = None

    for header, target in mapping.items():
        val = (raw.get(header) or "").strip()
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

    if "estimated_value" in out:
        parsed = _parse_int(out["estimated_value"])
        if parsed is None:
            del out["estimated_value"]
        else:
            out["estimated_value"] = parsed

    return out


def row_is_usable(row: dict) -> bool:
    """A row is worth importing if it has an address or any contact identifier."""
    return any(row.get(f) for f in
               ("address", "contact_email", "contact_phone", "contact_name", "owner_name"))
