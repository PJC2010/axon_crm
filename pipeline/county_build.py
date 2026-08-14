"""
County-wide shared-parcels cache build — every ZIP in hcad_properties cached
and coordinate-filled, with zero paid API calls.

FREE BY CONSTRUCTION, not by configuration: this module imports
pipeline.parcels (pure SQL) and the free Census batch pieces
(pipeline.geocode_batch + pipeline.http.post_file_text), and nothing else that
talks to a vendor. It never imports pipeline.geocode — the paid Google
fallback lives there — never reads a paid API key, and never writes
`properties`, so a county run cannot spend money and cannot materialize 1.6M
rows per tenant. tests/test_county_build.py asserts all of that from the
source; keep it true.

Runs OUTSIDE the web process — tools/build_parcel_cache.py from a developer
machine (Render EXTERNAL database URL) or a Render one-off job. The scheduler
shares the API instance's memory (see the OOM note in config.py), and a
county-wide pass has no business there. Every operation commits per ZIP, so a
killed run loses at most the ZIP in flight and rerunning IS the resume: each
pass is fill-only and idempotent.
"""
import logging

from psycopg2.extras import execute_values

from config import (CENSUS_BATCH_BENCHMARK, CENSUS_BATCH_GEOCODER_URL,
                    CENSUS_BATCH_TIMEOUT)
from pipeline import geocode_batch, parcels
from pipeline.addr import sql_has_situs
from pipeline.http import post_file_text

log = logging.getLogger(__name__)


def county_zips(conn) -> list[tuple[str, int]]:
    """Every ZIP in the HCAD mirror with its parcel count, in stable order.

    The stable ordering is what makes `start_after` a resume point. Non-5-digit
    values (bad source rows) are logged and still processed — the cache upsert
    is harmless for them, and skipping silently would hide the data problem.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT site_zip, COUNT(*) FROM hcad_properties "
            "WHERE site_zip IS NOT NULL AND site_zip <> '' "
            "GROUP BY site_zip ORDER BY site_zip"
        )
        rows = cur.fetchall()
    odd = [z for z, _ in rows if not (len(z) == 5 and z.isdigit())]
    if odd:
        log.warning("county build: %d non-5-digit ZIP value(s) in "
                    "hcad_properties (processing anyway): %s",
                    len(odd), ", ".join(odd[:10]))
    return rows


def census_fill_parcels(conn, zip_code: str) -> int:
    """Free Census-batch geocoding for a ZIP's parcels the centroids missed.

    Mirrors pipeline/geocode.py::_census_batch, but reads and writes the shared
    `parcels` cache instead of one tenant's properties: the result lands once,
    tenant-independent, and fans out through seed/sync like any cached fact.
    Results go to `parcels`, NOT hcad_parcel_centroids — that table stays a
    pure ArcGIS mirror its loader can TRUNCATE-reload.

    A failed batch is logged and skipped, never raised: rerunning the build
    heals it. No-situs parcels ("0 ACKLEY DR") are excluded up front — no
    geocoder can place them. Returns rows that gained coordinates.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, address, city, state, zip FROM parcels
            WHERE zip = %s
              AND latitude IS NULL
              AND {sql_has_situs('address')}
            """,
            (zip_code,),
        )
        rows = [{"id": r[0], "address": r[1], "city": r[2], "state": r[3],
                 "zip": r[4]} for r in cur.fetchall()]
    if not rows:
        return 0

    located: dict[str, tuple[float, float, float]] = {}
    batches = geocode_batch.chunk(rows)
    for i, batch in enumerate(batches, 1):
        text = post_file_text(
            CENSUS_BATCH_GEOCODER_URL,
            files={"addressFile":
                   ("addresses.csv", geocode_batch.build_payload(batch),
                    "text/csv")},
            data={"benchmark": CENSUS_BATCH_BENCHMARK},
            timeout=CENSUS_BATCH_TIMEOUT,
        )
        if not text:
            log.warning("census fill %s: batch %d/%d failed — a rerun heals it",
                        zip_code, i, len(batches))
            continue
        located.update(geocode_batch.parse_response(text))
    if not located:
        return 0

    values = []
    for pid, (lat, lng, confidence) in located.items():
        try:
            values.append((int(pid), lat, lng, confidence))
        except (TypeError, ValueError):
            continue   # an id the endpoint mangled — not worth losing the batch
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            UPDATE parcels p SET
                latitude           = v.lat,
                longitude          = v.lng,
                geocode_source     = 'census',
                geocode_confidence = v.confidence,
                enrichment_flags   = p.enrichment_flags
                                     || jsonb_build_object('geocode', 'census'),
                enriched_at        = NOW()
            FROM (VALUES %s) AS v(id, lat, lng, confidence)
            WHERE p.id = v.id AND p.latitude IS NULL
            """,
            values,
        )
        n = cur.rowcount
    conn.commit()
    log.info("parcels: %d coords filled from Census for ZIP %s", n, zip_code)
    return n


def build(conn, zips=None, start_after=None, census_fallback=True,
          min_match_rate=0.90, analyze_every=25, limit_zips=None) -> dict:
    """Build (or refresh) the shared cache for every ZIP, coordinates included.

    Per ZIP: ensure_from_hcad → fill_coords_from_centroids → Census fallback.
    Each operation commits itself, so an interruption loses at most the ZIP in
    flight and rerunning resumes; re-running a completed build changes nothing.

    Raises RuntimeError when the county-wide APN→centroid match rate lands
    under `min_match_rate` — a silently low-matching join is this design's top
    failure mode, so it fails loud instead of reporting success.
    """
    if zips:
        todo: list[tuple[str, int | None]] = [(z, None) for z in zips]
    else:
        todo = county_zips(conn)
    if start_after:
        todo = [(z, n) for z, n in todo if z > start_after]
    if limit_zips:
        todo = todo[:limit_zips]

    log.info("county build: %d ZIP(s)%s", len(todo),
             "" if census_fallback else " (census fallback off)")
    for i, (zip_code, hcad_count) in enumerate(todo, 1):
        cached = parcels.ensure_from_hcad(conn, zip_code)
        centroid_filled = parcels.fill_coords_from_centroids(conn, zip_code)
        census_filled = (census_fill_parcels(conn, zip_code)
                         if census_fallback else 0)
        cov = parcels.coverage(conn, zip_code)
        log.info("county build %d/%d %s: %s hcad rows -> %d cached, "
                 "+%d centroid, +%d census, %d/%d geocoded",
                 i, len(todo), zip_code,
                 hcad_count if hcad_count is not None else "?",
                 cached, centroid_filled, census_filled,
                 cov["geocoded"], cov["parcels"])
        if analyze_every and i % analyze_every == 0:
            _analyze(conn)

    rep = report(conn)
    try:
        rep["match_rate"] = assert_match_rate(rep, min_match_rate)
    except RuntimeError:
        for zip_code, address, apn in rep["unmatched_sample"]:
            log.error("unmatched apn sample: %s  %s  apn=%s",
                      zip_code, address, apn)
        raise
    return rep


def report(conn) -> dict:
    """County-wide parity numbers + a sample of unmatched APNs for debugging."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*),
                   COUNT(*) FILTER (WHERE p.parcel_apn IS NOT NULL),
                   COUNT(c.acct),
                   COUNT(p.latitude)
            FROM parcels p
            LEFT JOIN hcad_parcel_centroids c ON c.acct = p.parcel_apn
            """
        )
        total, with_apn, apn_matched, with_coords = cur.fetchone()
        cur.execute("SELECT COALESCE(geocode_source, '(none)'), COUNT(*) "
                    "FROM parcels GROUP BY 1 ORDER BY 2 DESC")
        sources = cur.fetchall()
        cur.execute("SELECT COUNT(*) FROM hcad_properties")
        hcad_total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM hcad_parcel_centroids")
        centroid_total = cur.fetchone()[0]
        # Mirrors the match-rate condition exactly — no coordinate filter, or a
        # row the Census pass healed would vanish from the sample while still
        # depressing the rate it is supposed to explain.
        cur.execute(
            """
            SELECT p.zip, p.address, p.parcel_apn
            FROM parcels p
            WHERE p.parcel_apn IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM hcad_parcel_centroids c
                              WHERE c.acct = p.parcel_apn)
            LIMIT 20
            """
        )
        unmatched_sample = cur.fetchall()
    return {
        "parcels_total": total,
        "with_apn": with_apn,
        "apn_matched": apn_matched,
        "with_coords": with_coords,
        "geocode_sources": sources,
        "hcad_properties": hcad_total,
        "hcad_parcel_centroids": centroid_total,
        "unmatched_sample": unmatched_sample,
    }


def assert_match_rate(rep: dict, min_rate: float) -> float:
    """APN→centroid match rate over parcels that HAVE an APN. Raises below
    `min_rate`.

    The denominator excludes NULL-APN parcels deliberately: an all-zero
    placeholder acct can never centroid-match by design, and the Census pass
    covers those rows — counting them would let a real join regression hide
    behind a fixed background of unmatchables.
    """
    with_apn, matched = rep["with_apn"], rep["apn_matched"]
    rate = (matched / with_apn) if with_apn else 0.0
    if rate < min_rate:
        raise RuntimeError(
            f"APN->centroid match rate {rate:.1%} is below {min_rate:.0%} "
            f"({matched:,} of {with_apn:,}). A silently low-matching join is "
            f"this design's top failure mode — inspect the unmatched-APN "
            f"sample (logged above / report()['unmatched_sample']) for "
            f"padding or format drift before trusting this build.")
    return rate


def _analyze(conn) -> None:
    # The build takes `parcels` from a few ZIPs to ~1.5M rows in one run;
    # without fresh stats the planner drifts off the partial-index nested loop
    # the centroid fill depends on.
    with conn.cursor() as cur:
        cur.execute("ANALYZE parcels")
    conn.commit()
    log.info("county build: ANALYZE parcels")
