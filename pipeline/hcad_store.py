"""
Read-only query interface for harris_county.duckdb (Harris CAD assessor data).

Two query functions:
  query_permits(zip_code)    → {address_norm: permit_count_24mo}
  query_properties(zip_code) → {address_norm: {field: value, ...}}

Both open the file in read_only=True so concurrent API/scheduler threads
can query simultaneously without blocking each other.
"""
import re
import logging
from pathlib import Path

import duckdb

from config import PERMIT_DB_PATH

log = logging.getLogger(__name__)


def db_exists(db_path: str | None = None) -> bool:
    path = Path(db_path or PERMIT_DB_PATH)
    return path.exists() and path.stat().st_size > 0


def normalize(address: str) -> str:
    """Lowercase + strip non-alphanumeric (except spaces). Single source of truth."""
    return re.sub(r'[^a-z0-9 ]', '', address.lower()).strip()


def query_permits(zip_code: str, db_path: str | None = None) -> dict[str, int]:
    """
    Return {address_norm: permit_count} for permits issued in the last 24 months.
    Excludes voided permits. Falls back to Postgres if DuckDB isn't available.
    """
    db_file = db_path or PERMIT_DB_PATH
    if db_exists(db_file):
        con = duckdb.connect(str(db_file), read_only=True)
        try:
            rows = con.execute("""
                SELECT
                    LOWER(TRIM(REGEXP_REPLACE(ps.site_address, '[^a-zA-Z0-9 ]', ' ', 'g'))) AS address_norm,
                    COUNT(p.id) AS permit_count
                FROM property_summary ps
                JOIN permits p ON ps.acct = p.acct
                WHERE ps.site_zip = ?
                  AND p.issue_date BETWEEN (CURRENT_DATE - INTERVAL 24 MONTH) AND CURRENT_DATE
                  AND p.status NOT IN ('V', 'v')
                GROUP BY address_norm
            """, [zip_code]).fetchall()
            return {r[0]: r[1] for r in rows}
        finally:
            con.close()

    # Fallback: query Postgres hcad_* tables
    return _pg_query_permits(zip_code)


def query_properties(zip_code: str, db_path: str | None = None) -> dict[str, dict]:
    """
    Return {address_norm: property_fields} for all properties in a ZIP.
    Fields map directly to nullable columns in our properties table.
    Falls back to Postgres if DuckDB isn't available.
    """
    db_file = db_path or PERMIT_DB_PATH
    if db_exists(db_file):
        con = duckdb.connect(str(db_file), read_only=True)
        try:
            rows = con.execute("""
                SELECT
                    LOWER(TRIM(REGEXP_REPLACE(site_address, '[^a-zA-Z0-9 ]', ' ', 'g'))) AS address_norm,
                    TRY_CAST(year_built AS INTEGER)   AS year_built,
                    building_sqft                     AS square_footage,
                    land_sqft                         AS lot_size,
                    tot_appr_val                      AS estimated_value,
                    last_sale_date,
                    owner_name,
                    likely_owner_occupied             AS owner_occupied
                FROM property_summary
                WHERE site_zip = ?
                  AND site_address IS NOT NULL
            """, [zip_code]).fetchall()

            cols = ["address_norm", "year_built", "square_footage", "lot_size",
                    "estimated_value", "last_sale_date", "owner_name", "owner_occupied"]
            result = {}
            for row in rows:
                d = dict(zip(cols, row))
                addr = d.pop("address_norm")
                if addr:
                    result[addr] = d
            return result
        finally:
            con.close()

    # Fallback: query Postgres hcad_* tables
    return _pg_query_properties(zip_code)


# ── Postgres fallback functions ──────────────────────────────────────────────

def _pg_query_permits(zip_code: str) -> dict[str, int]:
    """Query permit counts from Postgres hcad_* tables."""
    try:
        from pipeline.db import get_conn
        import psycopg2.extras
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    LOWER(TRIM(REGEXP_REPLACE(hp.site_address, '[^a-zA-Z0-9 ]', ' ', 'g'))) AS address_norm,
                    COUNT(hm.permit_id) AS permit_count
                FROM hcad_properties hp
                JOIN hcad_permits hm ON hm.acct = hp.acct
                WHERE hp.site_zip = %s
                  AND hm.issue_date BETWEEN (CURRENT_DATE - INTERVAL '24 months') AND CURRENT_DATE
                  AND hm.status NOT IN ('V', 'v')
                GROUP BY address_norm
            """, (zip_code,))
            result = {r[0]: r[1] for r in cur.fetchall()}
        conn.close()
        if result:
            log.info("Postgres HCAD permits: %d addresses for ZIP %s", len(result), zip_code)
        return result
    except Exception as e:
        log.warning("Postgres HCAD permit query failed: %s", e)
        return {}


def _pg_query_properties(zip_code: str) -> dict[str, dict]:
    """Query property data from Postgres hcad_* tables."""
    try:
        from pipeline.db import get_conn
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    LOWER(TRIM(REGEXP_REPLACE(site_address, '[^a-zA-Z0-9 ]', ' ', 'g'))) AS address_norm,
                    CAST(NULLIF(year_built, '') AS INTEGER) AS year_built,
                    building_sqft AS square_footage,
                    land_sqft AS lot_size,
                    tot_appr_val AS estimated_value,
                    last_sale_date,
                    owner_name,
                    likely_owner_occupied AS owner_occupied
                FROM hcad_properties
                WHERE site_zip = %s AND site_address IS NOT NULL
            """, (zip_code,))
            cols = ["address_norm", "year_built", "square_footage", "lot_size",
                    "estimated_value", "last_sale_date", "owner_name", "owner_occupied"]
            result = {}
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                addr = d.pop("address_norm")
                if addr:
                    result[addr] = d
        conn.close()
        if result:
            log.info("Postgres HCAD properties: %d records for ZIP %s", len(result), zip_code)
        return result
    except Exception as e:
        log.warning("Postgres HCAD property query failed: %s", e)
        return {}
