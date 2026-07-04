"""
Geocoding provider interface + async queue for tenant-entered addresses.

RentCast leads arrive already carrying latitude/longitude (persisted with
geocode_source='rentcast' at ingest), so they never touch this. Addresses a
tenant types in by hand — imported customers, manually created leads — arrive
without coordinates and are geocoded here, behind a provider interface so the
backing service is swappable (US Census by default; Google slots in if Census
confidence is poor).

Geocoding never happens in a request path (Section 6 of the plan). Callers
enqueue property ids; a background job drains the queue via `process_queue`.
"""
import logging
from abc import ABC, abstractmethod

from config import (
    GEOCODE_PROVIDER,
    CENSUS_GEOCODER_URL,
    GOOGLE_GEOCODE_KEY,
)
from pipeline.http import get_json

log = logging.getLogger(__name__)


# ── Provider interface ────────────────────────────────────────────────────────

class GeocodeProvider(ABC):
    """Turns a free-text address into (lat, lng, confidence) or None."""

    name: str = "base"

    @abstractmethod
    def geocode(self, address: str) -> tuple[float, float, float] | None:
        ...


class CensusGeocoder(GeocodeProvider):
    """US Census one-line geocoder — free, no key, handles US addresses well.

    Confidence is coarse (the Census API returns a match, not a score): an exact
    match reports 0.9, a non-exact tie-break 0.6. Enough for the breakdown to flag
    lower-confidence geocodes."""

    name = "census"

    def geocode(self, address: str) -> tuple[float, float, float] | None:
        if not address:
            return None
        data = get_json(
            CENSUS_GEOCODER_URL,
            params={"address": address, "benchmark": "Public_AR_Current", "format": "json"},
            timeout=15,
        )
        if not data:
            return None
        matches = (data.get("result") or {}).get("addressMatches") or []
        if not matches:
            return None
        best = matches[0]
        coords = best.get("coordinates") or {}
        lat, lng = coords.get("y"), coords.get("x")
        if lat is None or lng is None:
            return None
        confidence = 0.9 if str(best.get("matchType", "")).lower() == "exact" else 0.6
        return float(lat), float(lng), confidence


class GoogleGeocoder(GeocodeProvider):
    """Google Geocoding API — reuses GOOGLE_GEOCODE_KEY and the existing lookup
    in pipeline/geocode.py, so there is one Google code path, not two."""

    name = "google"

    def geocode(self, address: str) -> tuple[float, float, float] | None:
        if not GOOGLE_GEOCODE_KEY:
            return None
        from pipeline.geocode import _geocode
        result = _geocode(address)
        if not result:
            return None
        lat, lng = result
        return float(lat), float(lng), 0.85


_PROVIDERS: dict[str, type[GeocodeProvider]] = {
    "census": CensusGeocoder,
    "google": GoogleGeocoder,
}


def get_provider(name: str | None = None) -> GeocodeProvider:
    """Resolve the configured provider (default from config.GEOCODE_PROVIDER)."""
    key = (name or GEOCODE_PROVIDER or "census").strip().lower()
    provider_cls = _PROVIDERS.get(key, CensusGeocoder)
    return provider_cls()


def _full_address(row: dict) -> str:
    parts = [row.get("address"), row.get("city"), row.get("state"), row.get("zip")]
    return ", ".join(p for p in parts if p)


# ── Queue ─────────────────────────────────────────────────────────────────────

def enqueue_property(conn, property_id: int, account_id: int) -> bool:
    """Queue a single property for geocoding (idempotent). Returns True if a new
    queue row was created or an existing one was reset to 'queued'."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO geocode_queue (property_id, account_id, status) "
            "VALUES (%s, %s, 'queued') "
            "ON CONFLICT (property_id) DO UPDATE SET status = 'queued', "
            "  attempts = 0, last_error = NULL, queued_at = NOW(), processed_at = NULL "
            "WHERE geocode_queue.status <> 'queued' "
            "RETURNING id",
            (property_id, account_id),
        )
        created = cur.fetchone() is not None
    conn.commit()
    return created


def enqueue_missing(conn, account_id: int | None = None) -> int:
    """Queue every property that has an address but no coordinates (the backfill
    entry point). Scoped to one account, or all accounts when account_id is None.
    Skips properties already queued/pending. Returns the number enqueued."""
    params: list = []
    scope = ""
    if account_id is not None:
        scope = "AND p.account_id = %s"
        params.append(account_id)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO geocode_queue (property_id, account_id, status)
            SELECT p.id, p.account_id, 'queued'
            FROM properties p
            WHERE p.address IS NOT NULL AND p.address <> ''
              AND (p.latitude IS NULL OR p.longitude IS NULL)
              AND p.archived_at IS NULL
              {scope}
            ON CONFLICT (property_id) DO NOTHING
            """,
            params,
        )
        n = cur.rowcount
    conn.commit()
    return n


def process_queue(conn, limit: int = 200, provider: GeocodeProvider | None = None) -> dict:
    """Drain up to `limit` queued rows through the provider, writing coordinates
    back to properties. Returns a {geocoded, failed, remaining} summary.

    Each row is committed independently so a mid-batch failure doesn't lose prior
    progress. Rows that fail are marked 'failed' with the error for later retry.
    """
    provider = provider or get_provider()
    import psycopg2.extras

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT q.id AS queue_id, q.property_id, p.address, p.city, p.state, p.zip "
            "FROM geocode_queue q JOIN properties p ON p.id = q.property_id "
            "WHERE q.status = 'queued' ORDER BY q.queued_at LIMIT %s",
            (limit,),
        )
        rows = [dict(r) for r in cur.fetchall()]

    geocoded = failed = 0
    for row in rows:
        result = provider.geocode(_full_address(row))
        with conn.cursor() as cur:
            if result:
                lat, lng, confidence = result
                cur.execute(
                    "UPDATE properties SET latitude = %s, longitude = %s, "
                    "  geocode_source = %s, geocode_confidence = %s "
                    "WHERE id = %s AND (latitude IS NULL OR longitude IS NULL)",
                    (lat, lng, provider.name, confidence, row["property_id"]),
                )
                cur.execute(
                    "UPDATE geocode_queue SET status = 'done', processed_at = NOW(), "
                    "  attempts = attempts + 1 WHERE id = %s",
                    (row["queue_id"],),
                )
                geocoded += 1
            else:
                cur.execute(
                    "UPDATE geocode_queue SET status = 'failed', processed_at = NOW(), "
                    "  attempts = attempts + 1, last_error = %s WHERE id = %s",
                    ("no match", row["queue_id"]),
                )
                failed += 1
        conn.commit()

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM geocode_queue WHERE status = 'queued'")
        remaining = cur.fetchone()[0]

    log.info("Geocode queue: %d geocoded, %d failed, %d remaining", geocoded, failed, remaining)
    return {"geocoded": geocoded, "failed": failed, "remaining": remaining}
