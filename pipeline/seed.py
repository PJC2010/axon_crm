"""
Step 1 — Seed address list for a ZIP code.

Uses RentCast /properties endpoint to pull all known property records for a ZIP.
Falls back to a CSV file if RENTCAST_API_KEY is not set (useful for dev/testing).
"""
import csv
import logging
import time
from pathlib import Path

import requests

from config import RENTCAST_API_KEY, RENTCAST_BASE_URL
from pipeline.db import get_conn, upsert_properties

log = logging.getLogger(__name__)

BATCH_SIZE = 500   # RentCast max per request
TEST_LIMIT = None   # set to 3 (or any int) to cap records for testing


def seed_from_rentcast(zip_code: str, limit: int | None = None) -> int:
    """Pull property records from RentCast and upsert into DB. Returns count."""
    if not RENTCAST_API_KEY:
        raise ValueError("RENTCAST_API_KEY is not set. Use seed_from_csv() instead.")

    headers = {"X-Api-Key": RENTCAST_API_KEY, "Accept": "application/json"}
    offset = 0
    total = 0
    conn = get_conn()
    batch = min(limit, BATCH_SIZE) if limit else BATCH_SIZE

    while True:
        resp = requests.get(
            f"{RENTCAST_BASE_URL}/properties",
            headers=headers,
            params={"zipCode": zip_code, "limit": batch, "offset": offset},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        if not data:
            break

        rows = [_normalize_rentcast(p) for p in data]
        n = upsert_properties(conn, rows)
        total += n
        log.info("Seeded %d records (offset %d) for ZIP %s", n, offset, zip_code)

        if limit and total >= limit:
            break
        if len(data) < batch:
            break
        offset += batch
        time.sleep(0.2)   # be polite

    conn.close()
    return total


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

def _normalize_rentcast(p: dict) -> dict:
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
        "enrichment_flags": {"seed": "rentcast"},
    }
