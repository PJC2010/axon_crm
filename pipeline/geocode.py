"""
Step 3 — Geocoding.

Fills latitude, longitude, and geohash for properties that are missing them.

Bulk-first: the ZIP's whole backlog goes to the free Census *batch* endpoint in
10,000-address requests, and only the addresses Census cannot match fall through
to paid Google (bounded by GEOCODE_FALLBACK_MAX, and run in a small thread pool
rather than serially).

This replaced a strictly-serial one-Google-request-per-property loop that
measured ~2h52m and roughly $200 of Google Geocoding on ZIP 77449's 41,334
parcels. HCAD-seeded rows carry no coordinates, so *every* seeded property went
through it on every run.

Results are written with a single bulk UPDATE keyed on property id rather than
per-row upserts, so the write does not fan out into one round trip per distinct
column signature.
"""
import logging
from concurrent.futures import ThreadPoolExecutor

import psycopg2.extras

from config import (
    GOOGLE_GEOCODE_KEY, GOOGLE_GEOCODE_URL,
    CENSUS_BATCH_GEOCODER_URL, CENSUS_BATCH_BENCHMARK, CENSUS_BATCH_TIMEOUT,
    GEOCODE_FALLBACK_MAX, GEOCODE_FALLBACK_WORKERS,
)
from pipeline import geocode_batch
from pipeline.db import get_conn
from pipeline.http import get_json, post_file_text

log = logging.getLogger(__name__)

try:
    import geohash2 as _geohash
    def _encode(lat, lng): return _geohash.encode(lat, lng, precision=7)
except ImportError:
    def _encode(lat, lng): return None   # geohash optional


def enrich_geocode(zip_code: str, account_id: int) -> int:
    """Geocode this org's properties in `zip_code` that have no coordinates.

    Deliberately not restricted to the selected subset. This step must run before
    selection, because radius narrowing filters on the very coordinates it
    produces (pipeline/select.py::_within_radius), so it cannot be bounded by
    --top-n. Cost is bounded instead at the provider level: the Census batch is
    free and unmetered, and only the leftover misses reach paid Google, capped by
    GEOCODE_FALLBACK_MAX. Geocoding the whole ZIP is also worth doing on its own
    merits — coordinates persist, so later runs never repeat the work.
    """
    conn = get_conn()
    try:
        rows = _fetch_ungeocoded(conn, zip_code, account_id)
        if not rows:
            log.info("No properties need geocoding.")
            return 0

        log.info("Geocoding %d properties (Census batch, %d request(s))…",
                 len(rows), len(geocode_batch.chunk(rows)))

        # id -> (lat, lng, confidence, source)
        located = {
            pid: (lat, lng, conf, "census")
            for pid, (lat, lng, conf) in _census_batch(rows).items()
        }
        log.info("Census batch matched %d/%d", len(located), len(rows))

        missed = [r for r in rows if str(r["id"]) not in located]
        if missed:
            located.update({
                pid: (lat, lng, conf, "google")
                for pid, (lat, lng, conf) in _google_fallback(missed).items()
            })

        return _write(conn, located)
    finally:
        conn.close()


def _fetch_ungeocoded(conn, zip_code: str, account_id: int) -> list[dict]:
    """Only the five columns the geocoder needs — not SELECT *.

    The old path pulled every column of every row (~80 of them, including the
    JSONB blob) just to read an address.
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, address, city, state, zip FROM properties "
            "WHERE zip = %s AND account_id = %s "
            "  AND latitude IS NULL "
            "  AND address IS NOT NULL AND address <> '' "
            "  AND archived_at IS NULL",
            (zip_code, account_id),
        )
        return [dict(r) for r in cur.fetchall()]


def _census_batch(rows: list[dict]) -> dict[str, tuple[float, float, float]]:
    """Run every row through the free Census batch endpoint.

    A failed batch is logged and skipped rather than raised: those rows simply
    stay unmatched and fall through to the fallback, so one bad request cannot
    lose the whole ZIP.
    """
    located: dict[str, tuple[float, float, float]] = {}
    batches = geocode_batch.chunk(rows)
    for i, batch in enumerate(batches, 1):
        payload = geocode_batch.build_payload(
            [{"id": r["id"], **r} for r in batch]
        )
        text = post_file_text(
            CENSUS_BATCH_GEOCODER_URL,
            files={"addressFile": ("addresses.csv", payload, "text/csv")},
            data={"benchmark": CENSUS_BATCH_BENCHMARK},
            timeout=CENSUS_BATCH_TIMEOUT,
        )
        if not text:
            log.warning("Census batch %d/%d failed — those rows fall back",
                        i, len(batches))
            continue
        found = geocode_batch.parse_response(text)
        located.update(found)
        log.info("  batch %d/%d: %d/%d matched", i, len(batches), len(found), len(batch))
    return located


def _google_fallback(missed: list[dict]) -> dict[str, tuple[float, float, float]]:
    """Geocode Census misses through paid Google, capped and parallelized.

    Bounded by GEOCODE_FALLBACK_MAX because this is the only part of the step
    that costs money; set it to 0 to keep geocoding entirely free.
    """
    if not GOOGLE_GEOCODE_KEY:
        log.info("%d address(es) unmatched by Census; GOOGLE_GEOCODE_KEY not set "
                 "— leaving them ungeocoded.", len(missed))
        return {}
    if GEOCODE_FALLBACK_MAX <= 0:
        log.info("%d address(es) unmatched by Census; Google fallback disabled "
                 "(GEOCODE_FALLBACK_MAX=0).", len(missed))
        return {}

    capped = missed[:GEOCODE_FALLBACK_MAX]
    if len(missed) > len(capped):
        log.warning("%d address(es) unmatched by Census; geocoding %d via Google "
                    "(GEOCODE_FALLBACK_MAX). %d left for a later run.",
                    len(missed), len(capped), len(missed) - len(capped))
    else:
        log.info("Google fallback for %d unmatched address(es)…", len(capped))

    def _one(row):
        result = _geocode(_full_address(row))
        if not result:
            return None
        return str(row["id"]), (result[0], result[1], 0.85)

    out: dict[str, tuple[float, float, float]] = {}
    # Pure I/O-bound HTTP; requests releases the GIL, so a small pool turns a
    # serial crawl into a handful of concurrent round trips.
    with ThreadPoolExecutor(max_workers=max(1, GEOCODE_FALLBACK_WORKERS)) as pool:
        for res in pool.map(_one, capped):
            if res:
                out[res[0]] = res[1]
    log.info("Google fallback geocoded %d/%d", len(out), len(capped))
    return out


def _write(conn, located: dict[str, tuple[float, float, float, str]]) -> int:
    """Persist coordinates with one bulk UPDATE keyed on property id.

    Keyed on id rather than (address, zip) so this never re-runs the upsert
    column-signature grouping, and merges enrichment_flags rather than replacing
    them so earlier steps' provenance survives.
    """
    if not located:
        return 0

    values = [
        (int(pid), lat, lng, _encode(lat, lng), source, confidence)
        for pid, (lat, lng, confidence, source) in located.items()
    ]

    with conn.cursor() as cur:
        # fetch=True aggregates RETURNING across every internal page. cur.rowcount
        # would report only the last page (100 of 3,000 in testing), which would
        # then be logged and fed to the step timer as the row count.
        returned = psycopg2.extras.execute_values(
            cur,
            """
            UPDATE properties p SET
                latitude           = v.lat,
                longitude          = v.lng,
                geohash            = COALESCE(v.geohash, p.geohash),
                geocode_source     = v.source,
                geocode_confidence = v.confidence,
                enrichment_flags   = p.enrichment_flags
                                     || jsonb_build_object('geocode', v.source)
            FROM (VALUES %s) AS v(id, lat, lng, geohash, source, confidence)
            WHERE p.id = v.id
            RETURNING 1
            """,
            values,
            template="(%s::int, %s::double precision, %s::double precision, "
                     "%s::text, %s::text, %s::double precision)",
            fetch=True,
        )
        written = len(returned)
    conn.commit()
    log.info("Geocoded %d properties", written)
    return written


def _full_address(row: dict) -> str:
    return (f"{row.get('address', '')}, {row.get('city') or ''}, "
            f"{row.get('state') or ''} {row.get('zip') or ''}")


def geocode_address(address: str) -> tuple[float, float] | None:
    """Public one-shot geocode: turn a free-text address into (lat, lng).

    Returns None if no key is set or the lookup fails. Used by the selection
    step to resolve the center point for radius-from-address narrowing.
    """
    if not GOOGLE_GEOCODE_KEY:
        log.warning("GOOGLE_GEOCODE_KEY not set — cannot geocode center address.")
        return None
    return _geocode(address)


def _geocode(address: str) -> tuple[float, float] | None:
    data = get_json(
        GOOGLE_GEOCODE_URL,
        params={"address": address, "key": GOOGLE_GEOCODE_KEY},
        timeout=10,
    )
    if not data:
        return None
    results = data.get("results", [])
    if not results:
        return None
    try:
        loc = results[0]["geometry"]["location"]
        return loc["lat"], loc["lng"]
    except (KeyError, IndexError, TypeError) as e:
        log.warning("Geocoding parse failed for '%s': %s", address, e)
        return None
