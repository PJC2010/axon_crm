"""Fixture hygiene — what a recorded vendor payload may contain on disk.

Fixtures go into git history permanently and describe real Harris County
parcels once scripts/refresh_fixtures.py records live payloads, so this module
is the one place that decides what survives recording:

* **No credentials.** Keys travel in request headers/params, never bodies, but
  the sanitizers still refuse any key-shaped field so a vendor echoing one back
  can't land it on disk.
* **No owner PII** (TX SB 2121 makes this a hard requirement, not a nicety):
  owner names, mailing addresses, phone numbers, and skip-trace fields are
  stripped from RentCast and HCAD payloads. Only fields the scored factors and
  the address-echo/parcel checks actually consume survive — an allowlist, not
  a blocklist, so a new vendor field defaults to *dropped*.
* **Deterministic serialization**: sorted keys, floats pinned to 6 decimals,
  2-space indent, trailing newline — so re-recording produces a reviewable
  diff instead of noise.

tests/golden/test_scoring_golden.py enforces all of this against the committed
fixture tree, so a hand-edited fixture can't quietly reintroduce PII.
"""
import json
from pathlib import Path

# ── RentCast /properties record allowlist ─────────────────────────────────────
# Everything map_record (pipeline/reconcile.py) needs for the six scored
# factors plus the address-echo check (verify_record) and the shadow parcel
# check (assessorID). Deliberately absent: the whole `owner` object,
# `ownerName`, `hoa`, and tax history beyond `taxAssessments` (the value
# source). `ownerOccupied` is a boolean occupancy status, not PII, and feeds
# the absentee signal in vertical profiles.
RENTCAST_ALLOWED_KEYS = frozenset({
    "addressLine1", "formattedAddress", "city", "state", "zipCode",
    "latitude", "longitude",
    "yearBuilt", "squareFootage", "lotSize", "propertyType",
    "assessorID",
    "lastSaleDate", "lastSalePrice", "ownerOccupied",
    "taxAssessments",
    "features",
})
RENTCAST_ALLOWED_FEATURES = frozenset({
    "garageSpaces", "garageType", "pool",
})

# ── HCAD fixture allowlist ────────────────────────────────────────────────────
# Mirrors hcad_store.query_properties()'s output shape minus the PII columns
# (owner_name, mailing_address) — the harness passes None for those, which
# enrich_hcad's fill-only _backfill skips.
HCAD_ALLOWED_SUMMARY_KEYS = frozenset({
    "parcel_apn", "year_built", "square_footage", "lot_size",
    "estimated_value", "last_sale_date", "owner_occupied",
    "state_class", "neighborhood_code", "neighborhood_name",
})
HCAD_ALLOWED_EXTRA_KEYS = frozenset({
    "has_pool", "has_cracked_slab", "garage_spaces",
})

# Substrings that must never appear anywhere in a committed fixture file.
# Case-insensitive. Catches both credentials and the PII field names the
# allowlists exist to keep out.
FORBIDDEN_SUBSTRINGS = (
    "x-api-key", "api_key", "apikey",
    '"owner"', "ownername", "owner_name",
    "mailingaddress", "mailing_address",
    "phone", "skiptrace", "skip_trace", "ssn",
)


def sanitize_rentcast(payload):
    """Reduce a raw RentCast /properties response (a list of records) to the
    allowlisted fields. Unknown fields are dropped, never passed through."""
    if not isinstance(payload, list):
        return payload
    out = []
    for record in payload:
        if not isinstance(record, dict):
            continue
        kept = {k: v for k, v in record.items() if k in RENTCAST_ALLOWED_KEYS}
        features = record.get("features")
        if isinstance(features, dict):
            kept["features"] = {k: v for k, v in features.items()
                                if k in RENTCAST_ALLOWED_FEATURES}
        out.append(kept)
    return out


def sanitize_hcad(payload):
    """Reduce a recorded HCAD lookup ({property_summary, extra_features,
    permit_count_24mo}) to the allowlisted, PII-free fields."""
    if not isinstance(payload, dict):
        return payload
    out = {}
    summary = payload.get("property_summary")
    out["property_summary"] = (
        {k: v for k, v in summary.items() if k in HCAD_ALLOWED_SUMMARY_KEYS}
        if isinstance(summary, dict) else None
    )
    extra = payload.get("extra_features")
    out["extra_features"] = (
        {k: v for k, v in extra.items() if k in HCAD_ALLOWED_EXTRA_KEYS}
        if isinstance(extra, dict) else None
    )
    out["permit_count_24mo"] = payload.get("permit_count_24mo")
    return out


def _pin_floats(obj):
    """Round every float to 6 decimals so re-recording can't churn digits."""
    if isinstance(obj, float):
        return round(obj, 6)
    if isinstance(obj, dict):
        return {k: _pin_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_pin_floats(v) for v in obj]
    return obj


def canonical_json(obj) -> str:
    """The one serialization every fixture and golden file uses."""
    return json.dumps(_pin_floats(obj), sort_keys=True, indent=2,
                      ensure_ascii=False) + "\n"


def write_fixture(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(obj))
