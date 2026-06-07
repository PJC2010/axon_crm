#!/usr/bin/env python3
"""
Smart CRM — Data Acquisition Pipeline
Usage:
    python run_pipeline.py --zip 30066
    python run_pipeline.py --zip 30066 --vertical epoxy_flooring
    python run_pipeline.py --zip-file zips.txt --vertical epoxy_flooring
    python run_pipeline.py --zip 30066 --seed-csv /path/to/addresses.csv
    python run_pipeline.py --zip 30066 --permit-csv /path/to/permits.csv
    python run_pipeline.py --zip 30066 --skip seed,geocode
    python run_pipeline.py --zip 30066 --force-seed   # re-seed even if ZIP already exists
"""
import argparse
import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def _fmt_counters(counters: dict) -> str:
    """Render per-source property counters compactly for logs."""
    parts = []
    for src, c in counters.items():
        if c.get("skipped_no_key"):
            parts.append(f"{src}=skipped(no key)")
        else:
            parts.append(f"{src}: {c.get('updated', 0)} updated "
                         f"({c.get('ok', 0)} ok/{c.get('fail', 0)} fail)")
    return "; ".join(parts) or "nothing to do"


def _zip_already_seeded(zip_code: str) -> bool:
    """Return True if the ZIP already has properties in the DB."""
    from pipeline.db import get_conn
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM properties WHERE zip = %s LIMIT 1", (zip_code,))
        exists = cur.fetchone() is not None
    conn.close()
    return exists


def run_zip(zip_code: str, args) -> None:
    skip = set(s.strip() for s in (args.skip or "").split(",") if s.strip())
    top_n = getattr(args, "top_n", None)
    radius_mi = getattr(args, "radius", None)
    center_address = getattr(args, "address", None)
    capped = bool(top_n or (center_address and radius_mi))
    log.info("━━━  ZIP %s  ━━━", zip_code)

    if "seed" not in skip:
        from pipeline.seed import seed
        if not args.force_seed and _zip_already_seeded(zip_code):
            log.info("[1/7] Seed: skipped (ZIP already in DB — use --force-seed to re-fetch)")
        else:
            n = seed(zip_code, csv_path=args.seed_csv, limit=args.limit)
            log.info("[1/7] Seed: %d records", n)
    else:
        log.info("[1/7] Seed: skipped")

    if "census" not in skip:
        from pipeline.census import enrich_census
        n = enrich_census(zip_code)
        log.info("[2/7] Census: %d updated", n)
    else:
        log.info("[2/7] Census: skipped")

    if "geocode" not in skip:
        from pipeline.geocode import enrich_geocode
        n = enrich_geocode(zip_code)
        log.info("[3/7] Geocode: %d updated", n)
    else:
        log.info("[3/7] Geocode: skipped")

    # HCAD runs BEFORE RentCast/ATTOM — it's free (local DuckDB) and fills many
    # of the same fields (year_built, square_footage, estimated_value, etc.).
    # Running it first means fewer properties will have NULL fields, so RentCast
    # and ATTOM see a smaller work queue and make fewer paid API calls.
    if "hcad" not in skip:
        from pipeline.hcad_enrichment import enrich_hcad
        n = enrich_hcad(zip_code)
        log.info("[4/7] HCAD (free): %d fields backfilled", n)
    else:
        log.info("[4/7] HCAD: skipped")

    # Selection (volume control) — after all FREE steps, before any PAID step.
    if capped and "select" not in skip:
        from pipeline.db import get_conn
        from pipeline.select import select_for_enrichment
        from pipeline.geocode import geocode_address
        center = None
        if center_address and radius_mi:
            center = geocode_address(center_address)
            if center is None:
                log.warning("Could not geocode --address %r — radius filter skipped",
                            center_address)
        conn = get_conn()
        try:
            res = select_for_enrichment(conn, zip_code, top_n=top_n, center=center,
                                        radius_mi=radius_mi, vertical=args.vertical)
        finally:
            conn.close()
        log.info("[4.5/8] Selection: %s", res)

    if "property" not in skip:
        from pipeline.property import enrich_property
        counters = enrich_property(zip_code, selected_only=capped)
        log.info("[5/8] Property detail (RentCast/ATTOM): %s",
                 _fmt_counters(counters))
    else:
        log.info("[5/8] Property detail: skipped")

    if "permits" not in skip:
        from pipeline.permits import enrich_permits
        n = enrich_permits(zip_code, csv_path=args.permit_csv)
        log.info("[6/8] Permits: %d updated", n)
    else:
        log.info("[6/8] Permits: skipped")

    if "score" not in skip:
        from pipeline.scorer import score_zip
        n = score_zip(zip_code, vertical=args.vertical)
        log.info("[7/8] Scoring: %d scored", n)
    else:
        log.info("[7/8] Scoring: skipped")

    # Precision trim: cut the over-sampled selection back to exactly top_n using
    # the now-available real scores, before the paid skip-trace step.
    if capped and top_n and "score" not in skip:
        from pipeline.db import get_conn
        from pipeline.select import trim_to_top_n
        conn = get_conn()
        try:
            kept = trim_to_top_n(conn, zip_code, top_n)
        finally:
            conn.close()
        log.info("[7.5/8] Trim: kept top %d", kept)

    # Contact runs after scoring so the optional min-grade gate can apply.
    if "contact" not in skip:
        from pipeline.contact import enrich_contact
        c = enrich_contact(zip_code, selected_only=capped)
        log.info("[8/8] Contact: %d filled%s", c.get("updated", 0),
                 " (skipped: no provider)" if c.get("skipped_no_key") else "")
    else:
        log.info("[8/8] Contact: skipped")

    if "score" not in skip:
        from pipeline.coverage import fill_rates
        from pipeline.db import get_conn
        conn = get_conn()
        try:
            weak = sorted(
                ((f, r["pct"]) for f, r in fill_rates(conn, zip_code).items()),
                key=lambda kv: kv[1],
            )[:5]
        finally:
            conn.close()
        log.info("Weakest columns for ZIP %s: %s", zip_code,
                 ", ".join(f"{f} {p}%" for f, p in weak))


def main():
    parser = argparse.ArgumentParser(description="Smart CRM data pipeline")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--zip",      help="Single ZIP code to process")
    group.add_argument("--zip-file", help="Path to a file with one ZIP per line")

    parser.add_argument("--vertical",   default=None,
                        help="Scoring vertical (e.g. epoxy_flooring, pool_maintenance, solar)")
    parser.add_argument("--seed-csv",   default=None,
                        help="CSV file to seed addresses from (instead of RentCast API)")
    parser.add_argument("--permit-csv", default=None,
                        help="CSV file with permit counts (address, zip, permit_count)")
    parser.add_argument("--skip",       default="",
                        help="Comma-separated steps to skip: seed,census,geocode,hcad,select,property,permits,score,contact")
    parser.add_argument("--limit",      type=int, default=None,
                        help="Cap the number of seeded records (useful for testing)")
    parser.add_argument("--top-n",      type=int, default=None, dest="top_n",
                        help="Keep only the top N leads per ZIP before paid enrichment "
                             "(cuts RentCast/Attom/skip-trace cost)")
    parser.add_argument("--address",    default=None,
                        help="Center address for radius narrowing (with --radius)")
    parser.add_argument("--radius",     type=float, default=None,
                        help="Miles from --address; only homes inside the circle are enriched")
    parser.add_argument("--force-seed", action="store_true", default=False,
                        help="Re-fetch from RentCast even if the ZIP already has properties in the DB")

    args = parser.parse_args()

    if args.zip:
        zips = [args.zip.strip()]
    else:
        with open(args.zip_file) as f:
            zips = [line.strip() for line in f if line.strip()]

    if not zips:
        log.error("No ZIP codes provided.")
        sys.exit(1)

    start = time.time()
    for z in zips:
        run_zip(z, args)
    elapsed = time.time() - start
    log.info("Done. Processed %d ZIP(s) in %.1fs", len(zips), elapsed)


if __name__ == "__main__":
    main()
