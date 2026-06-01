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


def run_zip(zip_code: str, args) -> None:
    skip = set(s.strip() for s in (args.skip or "").split(",") if s.strip())
    log.info("━━━  ZIP %s  ━━━", zip_code)

    if "seed" not in skip:
        from pipeline.seed import seed
        n = seed(zip_code, csv_path=args.seed_csv, limit=args.limit)
        log.info("[1/6] Seed: %d records", n)
    else:
        log.info("[1/6] Seed: skipped")

    if "census" not in skip:
        from pipeline.census import enrich_census
        n = enrich_census(zip_code)
        log.info("[2/6] Census: %d updated", n)
    else:
        log.info("[2/6] Census: skipped")

    if "geocode" not in skip:
        from pipeline.geocode import enrich_geocode
        n = enrich_geocode(zip_code)
        log.info("[3/6] Geocode: %d updated", n)
    else:
        log.info("[3/6] Geocode: skipped")

    if "property" not in skip:
        from pipeline.property import enrich_property
        n = enrich_property(zip_code)
        log.info("[4/7] Property detail: %d updated", n)
    else:
        log.info("[4/7] Property detail: skipped")

    if "hcad" not in skip:
        from pipeline.hcad_enrichment import enrich_hcad
        n = enrich_hcad(zip_code)
        log.info("[4b/7] HCAD fallback: %d fields backfilled", n)
    else:
        log.info("[4b/7] HCAD fallback: skipped")

    if "permits" not in skip:
        from pipeline.permits import enrich_permits
        n = enrich_permits(zip_code, csv_path=args.permit_csv)
        log.info("[5/7] Permits: %d updated", n)
    else:
        log.info("[5/7] Permits: skipped")

    if "score" not in skip:
        from pipeline.scorer import score_zip
        n = score_zip(zip_code, vertical=args.vertical)
        log.info("[6/7] Scoring: %d scored", n)
    else:
        log.info("[6/7] Scoring: skipped")


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
                        help="Comma-separated steps to skip: seed,census,geocode,property,hcad,permits,score")
    parser.add_argument("--limit",      type=int, default=None,
                        help="Cap the number of seeded records (useful for testing)")

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
