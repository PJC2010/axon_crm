#!/usr/bin/env python3
"""
Build the shared parcels cache for every Harris County ZIP — coordinates
included, with zero geocode API spend.

Per ZIP: cache the HCAD rows (parcels.ensure_from_hcad), fill coordinates from
the centroid mirror (parcels.fill_coords_from_centroids), then free Census
batch geocoding for whatever the centroids missed. Every pass is fill-only and
idempotent and every step commits per ZIP, so Ctrl-C loses at most one ZIP and
rerunning resumes. Exits nonzero — after logging an unmatched-APN sample — if
the county-wide APN→centroid match rate lands under --min-match-rate.

This is the county-wide "shared geocode pass" and it runs OUTSIDE the web
process: from your machine against Render's EXTERNAL database URL, or as a
Render one-off job. Never from the API instance (see the OOM note in
config.py). It creates NO tenant rows — per-account materialization stays
on-demand through seed_account, exactly as before.

Prerequisites, in order:
  1. `python db/migrate.py` against the target database.
  2. hcad_properties loaded    (tools/load_hcad_to_postgres.py).
  3. hcad_parcel_centroids loaded (tools/load_parcel_centroids.py).

Usage:
    python tools/build_parcel_cache.py --dsn "postgresql://user:pass@host/db"
    python tools/build_parcel_cache.py --zips 77396,77449     # subset / smoke
    python tools/build_parcel_cache.py --start-after 77338    # resume manually
    python tools/build_parcel_cache.py --no-census-fallback   # centroids only
"""
import argparse
import logging
import os
import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import county_build  # noqa: E402


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(description="County-wide parcels cache build")
    p.add_argument("--dsn", default=os.getenv("DATABASE_URL"),
                   help="Target Postgres DSN (default: $DATABASE_URL). Use "
                        "Render's EXTERNAL database URL from your machine.")
    p.add_argument("--zips",
                   help="Comma-separated ZIPs to build (default: every ZIP in "
                        "hcad_properties)")
    p.add_argument("--start-after", dest="start_after", metavar="ZIP",
                   help="Skip ZIPs sorting at or before this one (manual resume)")
    p.add_argument("--limit-zips", type=int, dest="limit_zips", metavar="N",
                   help="Process at most N ZIPs this run (smoke tests)")
    p.add_argument("--no-census-fallback", action="store_true",
                   help="Skip the free Census pass for parcels the centroids "
                        "missed (faster first pass; rerun later with it on)")
    p.add_argument("--min-match-rate", type=float, default=0.90,
                   help="Fail (nonzero exit) if the county-wide APN->centroid "
                        "match rate is below this (default: %(default)s)")
    args = p.parse_args()
    if not args.dsn:
        p.error("no target database: pass --dsn or set DATABASE_URL")

    zips = ([z.strip() for z in args.zips.split(",") if z.strip()]
            if args.zips else None)
    conn = psycopg2.connect(args.dsn)
    try:
        rep = county_build.build(
            conn, zips=zips, start_after=args.start_after,
            census_fallback=not args.no_census_fallback,
            min_match_rate=args.min_match_rate, limit_zips=args.limit_zips)
    except RuntimeError as e:
        sys.exit(f"error: {e}")
    finally:
        conn.close()

    print("\nCounty cache report:", flush=True)
    print(f"  parcels:                 {rep['parcels_total']:>12,}", flush=True)
    print(f"  with APN:                {rep['with_apn']:>12,}", flush=True)
    print(f"  APN matched to centroid: {rep['apn_matched']:>12,}   "
          f"({rep['match_rate']:.1%})", flush=True)
    print(f"  with coordinates:        {rep['with_coords']:>12,}", flush=True)
    print(f"  hcad_properties:         {rep['hcad_properties']:>12,}", flush=True)
    print(f"  centroid mirror:         {rep['hcad_parcel_centroids']:>12,}",
          flush=True)
    print("  geocode sources:", flush=True)
    for source, n in rep["geocode_sources"]:
        print(f"    {source:<16}       {n:>12,}", flush=True)
    if rep["unmatched_sample"]:
        print("  unmatched-APN sample (zip, address, apn):", flush=True)
        for zip_code, address, apn in rep["unmatched_sample"]:
            print(f"    {zip_code}  {address}  {apn}", flush=True)


if __name__ == "__main__":
    main()
