"""
Step 3 — Geocoding via Google Maps Geocoding API.

Fills latitude, longitude, and geohash for properties that are missing them.
"""
import logging
import time

import requests

from config import GOOGLE_GEOCODE_KEY, GOOGLE_GEOCODE_URL
from pipeline.db import get_conn, fetch_missing_field, upsert_properties

log = logging.getLogger(__name__)

try:
    import geohash2 as _geohash
    def _encode(lat, lng): return _geohash.encode(lat, lng, precision=7)
except ImportError:
    def _encode(lat, lng): return None   # geohash optional


def enrich_geocode(zip_code: str | None = None) -> int:
    if not GOOGLE_GEOCODE_KEY:
        log.warning("GOOGLE_GEOCODE_KEY not set — skipping geocoding step.")
        return 0

    conn = get_conn()
    rows = fetch_missing_field(conn, "latitude", zip_code)
    if not rows:
        log.info("No properties need geocoding.")
        conn.close()
        return 0

    log.info("Geocoding %d properties…", len(rows))
    updates = []
    for row in rows:
        full_address = f"{row['address']}, {row.get('city', '')}, {row.get('state', '')} {row.get('zip', '')}"
        result = _geocode(full_address)
        if result:
            lat, lng = result
            updates.append({
                "address":  row["address"],
                "zip":      row["zip"],
                "latitude": lat,
                "longitude": lng,
                "geohash":  _encode(lat, lng),
                "enrichment_flags": {"geocode": "google"},
            })
        time.sleep(0.05)   # ~20 req/s, well under free tier limit

    n = upsert_properties(conn, updates)
    conn.close()
    log.info("Geocoded %d properties", n)
    return n


def _geocode(address: str) -> tuple[float, float] | None:
    try:
        resp = requests.get(
            GOOGLE_GEOCODE_URL,
            params={"address": address, "key": GOOGLE_GEOCODE_KEY},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            return None
        loc = results[0]["geometry"]["location"]
        return loc["lat"], loc["lng"]
    except Exception as e:
        log.warning("Geocoding failed for '%s': %s", address, e)
        return None
