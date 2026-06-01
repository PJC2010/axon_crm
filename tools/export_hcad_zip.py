#!/usr/bin/env python3
"""
Export HCAD data for specific ZIP codes from the local DuckDB into CSV files
that can be uploaded to Render's Postgres via the /api/hcad/upload endpoint.

Usage:
    python tools/export_hcad_zip.py 77396
    python tools/export_hcad_zip.py 77396 77002 77063
    python tools/export_hcad_zip.py --all       # export all ZIPs (large!)

Output: tools/hcad_export/properties_{zip}.csv and tools/hcad_export/permits_{zip}.csv
"""
import sys
import argparse
from pathlib import Path

import duckdb

from config import PERMIT_DB_PATH

EXPORT_DIR = Path(__file__).parent / "hcad_export"


def export_zip(con, zip_code: str) -> tuple[int, int]:
    EXPORT_DIR.mkdir(exist_ok=True)

    # Properties
    props_path = EXPORT_DIR / f"properties_{zip_code}.csv"
    con.execute(f"""
        COPY (
            SELECT acct, site_address, site_zip, year_built, building_sqft, land_sqft,
                   tot_appr_val, last_sale_date, owner_name, likely_owner_occupied
            FROM property_summary
            WHERE site_zip = '{zip_code}' AND site_address IS NOT NULL
        ) TO '{props_path}' (FORMAT CSV, HEADER TRUE)
    """)
    props_count = con.execute(f"SELECT COUNT(*) FROM property_summary WHERE site_zip = '{zip_code}'").fetchone()[0]

    # Permits (joined to properties to filter by ZIP)
    permits_path = EXPORT_DIR / f"permits_{zip_code}.csv"
    con.execute(f"""
        COPY (
            SELECT p.acct, p.id AS permit_id, p.status, p.issue_date,
                   p.permit_type, p.permit_tp_descr AS description
            FROM permits p
            JOIN property_summary ps ON ps.acct = p.acct
            WHERE ps.site_zip = '{zip_code}' AND p.issue_date IS NOT NULL
        ) TO '{permits_path}' (FORMAT CSV, HEADER TRUE)
    """)
    permits_count = con.execute(f"""
        SELECT COUNT(*) FROM permits p
        JOIN property_summary ps ON ps.acct = p.acct
        WHERE ps.site_zip = '{zip_code}'
    """).fetchone()[0]

    print(f"  ZIP {zip_code}: {props_count:,} properties, {permits_count:,} permits")
    return props_count, permits_count


def main():
    parser = argparse.ArgumentParser(description="Export HCAD data per ZIP")
    parser.add_argument("zips", nargs="*", help="ZIP codes to export")
    parser.add_argument("--all", action="store_true", help="Export all ZIPs")
    args = parser.parse_args()

    con = duckdb.connect(str(PERMIT_DB_PATH), read_only=True)

    if args.all:
        zips = [r[0] for r in con.execute(
            "SELECT DISTINCT site_zip FROM property_summary WHERE site_zip IS NOT NULL ORDER BY site_zip"
        ).fetchall()]
    elif args.zips:
        zips = args.zips
    else:
        parser.error("Provide ZIP codes or --all")

    total_p, total_m = 0, 0
    for z in zips:
        p, m = export_zip(con, z)
        total_p += p
        total_m += m

    con.close()
    print(f"\nExported {len(zips)} ZIP(s): {total_p:,} properties, {total_m:,} permits")
    print(f"Files in: {EXPORT_DIR}/")


if __name__ == "__main__":
    main()
