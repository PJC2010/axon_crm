"""
Step 1 — Seed address list for a ZIP code.

Uses RentCast /properties to pull all known property records for a ZIP. When a
ZIP returns very few records, optionally expands the search to nearby/city ZIPs
so downstream enrichment has enough to work with. Falls back to a CSV file if
RENTCAST_API_KEY is not set (useful for dev/testing).
"""
import csv
import logging
import time
from pathlib import Path

from config import (
    RENTCAST_API_KEY, RENTCAST_BASE_URL, SEED_PROPERTY_TYPES,
    SEED_EXPAND_ENABLED, SEED_EXPAND_THRESHOLD, SEED_EXPAND_TARGET,
    SEED_EXPAND_RADIUS_MI, SEED_EXPAND_MAX_ZIPS,
)
from pipeline.db import get_conn, upsert_properties
from pipeline.http import get_json

log = logging.getLogger(__name__)

BATCH_SIZE = 500   # RentCast max per request


def _wanted_type(property_type: str | None) -> bool:
    """True if a record's propertyType should be seeded.

    The allowlist lives in SEED_PROPERTY_TYPES; "*" (or empty) disables the
    filter and seeds everything. A record with no propertyType is kept — we have
    no grounds to drop it, and dropping would lose legit homes with missing data.
    """
    if not SEED_PROPERTY_TYPES or "*" in SEED_PROPERTY_TYPES:
        return True
    if not property_type:
        return True
    return property_type in SEED_PROPERTY_TYPES


def _seed_one_zip(conn, zip_code: str, limit: int | None = None,
                  origin_zip: str | None = None) -> int:
    """Paginate RentCast for a single ZIP and upsert. Returns rows affected.

    `origin_zip` (set when this ZIP was reached via expansion) is recorded in
    enrichment_flags; each row keeps its own true `zip` from RentCast.
    """
    headers = {"X-Api-Key": RENTCAST_API_KEY, "Accept": "application/json"}
    offset = 0
    total = 0
    batch = min(limit, BATCH_SIZE) if limit else BATCH_SIZE

    while True:
        data = get_json(
            f"{RENTCAST_BASE_URL}/properties",
            headers=headers,
            params={"zipCode": zip_code, "limit": batch, "offset": offset},
            timeout=30,
        )
        if not data:
            break

        # Drop unwanted property types (e.g. Apartment, Multi-Family) before they
        # reach the DB and incur paid enrichment downstream.
        wanted = [p for p in data if _wanted_type(p.get("propertyType"))]
        dropped = len(data) - len(wanted)
        if dropped:
            log.info("Skipped %d non-target property type(s) for ZIP %s",
                     dropped, zip_code)

        rows = [_normalize_rentcast(p, origin_zip) for p in wanted]
        n = upsert_properties(conn, rows)
        total += n
        log.info("Seeded %d records (offset %d) for ZIP %s", n, offset, zip_code)

        if limit and total >= limit:
            break
        if len(data) < batch:
            break
        offset += batch
        time.sleep(0.2)   # be polite

    return total


def seed_from_rentcast(zip_code: str, limit: int | None = None) -> int:
    """Seed `zip_code`, expanding to nearby ZIPs when the result is thin."""
    if not RENTCAST_API_KEY:
        raise ValueError("RENTCAST_API_KEY is not set. Use seed_from_csv() instead.")

    conn = get_conn()
    try:
        total = _seed_one_zip(conn, zip_code, limit=limit)

        # Expansion only when not explicitly limited (limit is a test/cost cap).
        if (limit is None and SEED_EXPAND_ENABLED
                and total < SEED_EXPAND_THRESHOLD):
            total += _expand_seed(conn, zip_code, already=total)
    finally:
        conn.close()
    return total


def _expand_seed(conn, zip_code: str, already: int) -> int:
    """Seed nearby ZIPs (then same-city ZIPs) until SEED_EXPAND_TARGET is met."""
    from pipeline import geo_expand

    if not geo_expand.available():
        log.warning("Seed expansion requested but `uszipcode` is not installed — "
                    "skipping. `pip install uszipcode` to enable.")
        return 0

    candidates = geo_expand.nearby_zips(
        zip_code, radius_miles=SEED_EXPAND_RADIUS_MI, max_zips=SEED_EXPAND_MAX_ZIPS,
    )
    if not candidates:
        candidates = geo_expand.city_zips(zip_code, max_zips=SEED_EXPAND_MAX_ZIPS)

    log.info("ZIP %s thin (%d rows); expanding to %d nearby ZIP(s)",
             zip_code, already, len(candidates))

    gained = 0
    for z in candidates:
        if already + gained >= SEED_EXPAND_TARGET:
            break
        gained += _seed_one_zip(conn, z, origin_zip=zip_code)
    return gained


def seed_from_csv(csv_path: str, zip_code: str | None = None) -> int:
    """
    Load addresses from a CSV file. Expected columns (case-insensitive):
    address, city, state, zip  (plus any optional property fields).
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(csv_path)

    conn = get_conn()
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            row = {k.lower().strip(): v.strip() for k, v in raw.items() if v}
            if zip_code and row.get("zip") != zip_code:
                continue
            # CSV headers vary: accept either property_type or propertytype.
            ptype = row.get("property_type") or row.get("propertytype")
            if not _wanted_type(ptype):
                continue
            rows.append(row)

    n = upsert_properties(conn, rows)
    conn.close()
    log.info("Seeded %d records from %s", n, csv_path)
    return n


def seed(zip_code: str, csv_path: str | None = None, limit: int | None = None) -> int:
    if csv_path:
        return seed_from_csv(csv_path, zip_code)
    return seed_from_rentcast(zip_code, limit=limit)


# ── Normalizers ───────────────────────────────────────────────────────────────

def _normalize_rentcast(p: dict, origin_zip: str | None = None) -> dict:
    flags = {"seed": "rentcast"}
    if origin_zip and p.get("zipCode") != origin_zip:
        flags["seed_origin_zip"] = origin_zip
    # Garage data lives in the nested `features` object in the records response.
    features = p.get("features") or {}
    return {
        "address":         p.get("addressLine1", ""),
        "city":            p.get("city", ""),
        "state":           p.get("state", ""),
        "zip":             p.get("zipCode", ""),
        "latitude":        p.get("latitude"),
        "longitude":       p.get("longitude"),
        "year_built":      p.get("yearBuilt"),
        "square_footage":  p.get("squareFootage"),
        "property_type":   p.get("propertyType"),
        "estimated_value": p.get("price"),
        "last_sale_date":  p.get("lastSaleDate"),
        "last_sale_price": p.get("lastSalePrice"),
        "owner_name":      p.get("ownerName"),
        "owner_occupied":  p.get("ownerOccupied"),
        "garage_spaces":   features.get("garageSpaces"),
        "garage_type":     features.get("garageType"),
        "enrichment_flags": flags,
    }
