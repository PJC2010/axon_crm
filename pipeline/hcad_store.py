"""
Read-only query interface for harris_county.duckdb (Harris CAD assessor data).

Two query functions:
  query_permits(zip_code)    → {address_norm: permit_count_24mo}
  query_properties(zip_code) → {address_norm: {field: value, ...}}

Both open the file in read_only=True so concurrent API/scheduler threads
can query simultaneously without blocking each other.
"""
import logging
from pathlib import Path

import duckdb

from config import PERMIT_DB_PATH, GARAGE_SQFT_PER_SPACE, MAX_GARAGE_SPACES
from pipeline.addr import normalize, sql_normalize   # shared single source of truth

log = logging.getLogger(__name__)

# Match keys, built in SQL from the one rule `normalize` implements.
#
# Every query below used to inline its own expression that replaced punctuation
# with a SPACE and never collapsed whitespace, while its callers
# (hcad_enrichment.py, permits.py) looked the results up with the Python
# normalizer, which DROPS punctuation and DOES collapse. The two disagreed on any
# address carrying punctuation or a double space — "500 W 12TH 1/2 ST" keyed as
# "500 w 12th 1 2 st" but was looked up as "500 w 12th 12 st" — so those parcels
# silently failed to match and the free county data never landed on them. Worse
# than a coverage gap: the field stayed NULL, which made the row eligible for the
# paid source, so we were billed for data HCAD had already given us.
#
# Derived, never hand-copied, so the two can no longer drift apart.
_ADDR_NORM_PS = sql_normalize("ps.site_address")
_ADDR_NORM_HP = sql_normalize("hp.site_address")
_ADDR_NORM = sql_normalize("site_address")


def garage_spaces_from_sqft(sqft) -> int:
    """Convert HCAD extra-feature garage units (square feet) to a space count.

    HCAD's `uts` column is the valuation unit for the feature — for garages
    that is area in sqft, not a car count (a typical 2-car garage is ~480
    sqft). Returns 0 when no garage area was recorded.
    """
    sqft = int(sqft or 0)
    if sqft <= 0:
        return 0
    return max(1, min(MAX_GARAGE_SPACES, round(sqft / GARAGE_SQFT_PER_SPACE)))


def db_exists(db_path: str | None = None) -> bool:
    """True only when a real, non-empty DuckDB file is configured.

    An empty PERMIT_DB_PATH means "no DuckDB, use the Postgres mirror" — that is
    exactly how Render is configured, since the web filesystem is ephemeral. It
    must be handled explicitly: Path("") resolves to the current directory, which
    exists and reports a non-zero size, so the naive check said the DuckDB was
    present and every query then died in duckdb.connect("", read_only=True) with
    "Cannot launch in-memory database in read-only mode" — raised before the
    callers' fallback try/except, so it took the whole pipeline run down instead
    of degrading to Postgres.

    is_file() (not exists()) for the same reason: a directory is not a database.
    """
    raw = (db_path or PERMIT_DB_PATH or "").strip()
    if not raw:
        return False
    path = Path(raw)
    return path.is_file() and path.stat().st_size > 0


def hcad_available(db_path: str | None = None) -> bool:
    """True if any HCAD source has data — the local DuckDB file, or the Postgres
    `hcad_properties` mirror with at least one row.

    Used by the startup guard so a deploy that selects HCAD seeding but has no
    data loaded fails loudly instead of silently seeding 0 rows.
    """
    if db_exists(db_path):
        return True
    try:
        from pipeline.db import get_conn
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM hcad_properties LIMIT 1")
                return cur.fetchone() is not None
        finally:
            conn.close()
    except Exception as e:
        log.debug("hcad_available Postgres check failed: %s", e)
        return False



def query_permits(zip_code: str, db_path: str | None = None) -> dict[str, int]:
    """
    Return {address_norm: permit_count} for permits issued in the last 24 months.
    Excludes voided permits. Falls back to Postgres if DuckDB isn't available.
    """
    db_file = db_path or PERMIT_DB_PATH
    if db_exists(db_file):
        con = duckdb.connect(str(db_file), read_only=True)
        try:
            rows = con.execute(f"""
                SELECT
                    {_ADDR_NORM_PS} AS address_norm,
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
            rows = con.execute(f"""
                SELECT
                    {_ADDR_NORM_PS} AS address_norm,
                    TRY_CAST(ps.year_built AS INTEGER)   AS year_built,
                    ps.building_sqft                     AS square_footage,
                    ps.land_sqft                         AS lot_size,
                    ps.tot_appr_val                      AS estimated_value,
                    ps.last_sale_date,
                    ps.owner_name,
                    ps.likely_owner_occupied             AS owner_occupied,
                    NULLIF(CONCAT_WS(', ',
                        NULLIF(TRIM(ps.mail_addr), ''),
                        NULLIF(TRIM(ps.mail_city), ''),
                        NULLIF(TRIM(CONCAT_WS(' ', NULLIF(TRIM(ps.mail_state), ''),
                                                   NULLIF(TRIM(ps.mail_zip), ''))), '')
                    ), '')                               AS mailing_address,
                    ps.neighborhood_code,
                    nc.dscr                              AS neighborhood_name
                FROM property_summary ps
                LEFT JOIN neighborhood_codes nc ON nc.cd = ps.neighborhood_code
                WHERE ps.site_zip = ?
                  AND ps.site_address IS NOT NULL
            """, [zip_code]).fetchall()

            cols = ["address_norm", "year_built", "square_footage", "lot_size",
                    "estimated_value", "last_sale_date", "owner_name", "owner_occupied",
                    "mailing_address", "neighborhood_code", "neighborhood_name"]
            result = {}
            for row in rows:
                d = dict(zip(cols, row))
                addr = d.pop("address_norm")
                if addr:
                    result[addr] = d
            return result
        except duckdb.CatalogException:
            # neighborhood_codes table absent (built without real_neighborhood_code.txt)
            # — retry without the JOIN so the rest of enrichment still works.
            return _duckdb_query_properties_no_nbhd(con, zip_code)
        finally:
            con.close()

    # Fallback: query Postgres hcad_* tables
    return _pg_query_properties(zip_code)


def _duckdb_query_properties_no_nbhd(con, zip_code: str) -> dict[str, dict]:
    rows = con.execute(f"""
        SELECT
            {_ADDR_NORM} AS address_norm,
            TRY_CAST(year_built AS INTEGER)   AS year_built,
            building_sqft                     AS square_footage,
            land_sqft                         AS lot_size,
            tot_appr_val                      AS estimated_value,
            last_sale_date,
            owner_name,
            likely_owner_occupied             AS owner_occupied,
            NULLIF(CONCAT_WS(', ',
                NULLIF(TRIM(mail_addr), ''),
                NULLIF(TRIM(mail_city), ''),
                NULLIF(TRIM(CONCAT_WS(' ', NULLIF(TRIM(mail_state), ''),
                                           NULLIF(TRIM(mail_zip), ''))), '')
            ), '')                            AS mailing_address,
            neighborhood_code,
            NULL::VARCHAR                     AS neighborhood_name
        FROM property_summary
        WHERE site_zip = ?
          AND site_address IS NOT NULL
    """, [zip_code]).fetchall()

    cols = ["address_norm", "year_built", "square_footage", "lot_size",
            "estimated_value", "last_sale_date", "owner_name", "owner_occupied",
            "mailing_address", "neighborhood_code", "neighborhood_name"]
    result = {}
    for row in rows:
        d = dict(zip(cols, row))
        addr = d.pop("address_norm")
        if addr:
            result[addr] = d
    return result


def query_extra_features(zip_code: str, db_path: str | None = None) -> dict[str, dict]:
    """
    Return {address_norm: {has_pool, has_cracked_slab, garage_spaces}} for a ZIP.

    Sources: extra_features table in DuckDB (joined to property_summary), or
    hcad_extra_features in Postgres. Gracefully returns {} if neither is available.

    Garage detection: l_dscr LIKE '%GARAGE%' — HCAD's `uts` units are garage
    square feet, converted to a space count via garage_spaces_from_sqft().
    Pool detection:   l_dscr LIKE '%POOL%'
    Cracked slab:     l_dscr LIKE '%CRACKED SLAB%' or s_dscr LIKE '%CRACK%'
    """
    db_file = db_path or PERMIT_DB_PATH
    if db_exists(db_file):
        con = duckdb.connect(str(db_file), read_only=True)
        try:
            rows = con.execute(f"""
                SELECT
                    {_ADDR_NORM_PS} AS address_norm,
                    BOOL_OR(UPPER(ef.l_dscr) LIKE '%POOL%')                                  AS has_pool,
                    BOOL_OR(UPPER(ef.l_dscr) LIKE '%CRACKED SLAB%'
                            OR UPPER(ef.s_dscr) LIKE '%CRACK%')                             AS has_cracked_slab,
                    COALESCE(SUM(
                        CASE WHEN UPPER(ef.l_dscr) LIKE '%GARAGE%'
                             THEN TRY_CAST(ef.uts AS INTEGER) ELSE 0 END
                    ), 0)                                                                     AS garage_sqft
                FROM property_summary ps
                JOIN extra_features ef ON ps.acct = ef.acct
                WHERE ps.site_zip = ?
                GROUP BY address_norm
            """, [zip_code]).fetchall()
            return {
                r[0]: {"has_pool": bool(r[1]), "has_cracked_slab": bool(r[2]),
                       "garage_spaces": garage_spaces_from_sqft(r[3])}
                for r in rows if r[0]
            }
        except Exception as e:
            log.debug("DuckDB extra_features query skipped (table may not exist): %s", e)
        finally:
            con.close()

    return _pg_query_extra_features(zip_code)


# ── Region selector (named HCAD neighborhoods) ───────────────────────────────
# These power the "pick an area by name" UI and the free seed-from-HCAD path.
# They read the local DuckDB only — zero paid API calls. A region is one HCAD
# neighborhood_code (named via the neighborhood_codes lookup); it may span a few
# ZIPs, so each region carries the list of ZIPs it touches.

REGION_MIN_PARCELS = 25   # drop tiny/noise neighborhoods from the selector


def list_regions(db_path: str | None = None) -> list[dict]:
    """Selectable named neighborhoods for Harris County, straight from DuckDB.

    Groups property_summary by neighborhood_code and resolves a human-readable
    name via the neighborhood_codes lookup. Returns, sorted by name:
        [{region_id, name, parcel_count, zips: [...]}, ...]
    Falls back to raw codes (no names) if the lookup table is absent, and to the
    Postgres mirror if the DuckDB file is unavailable.
    """
    db_file = db_path or PERMIT_DB_PATH
    if db_exists(db_file):
        con = duckdb.connect(str(db_file), read_only=True)
        try:
            return _duckdb_list_regions(con, joined=True)
        except duckdb.CatalogException:
            # neighborhood_codes table absent — retry without names.
            return _duckdb_list_regions(con, joined=False)
        finally:
            con.close()
    return _pg_list_regions()


def _duckdb_list_regions(con, joined: bool) -> list[dict]:
    name_expr = "COALESCE(nc.dscr, ps.neighborhood_code)" if joined else "ps.neighborhood_code"
    join_clause = "LEFT JOIN neighborhood_codes nc ON nc.cd = ps.neighborhood_code" if joined else ""
    group_extra = ", nc.dscr" if joined else ""
    rows = con.execute(f"""
        SELECT ps.neighborhood_code            AS region_id,
               {name_expr}                       AS name,
               COUNT(*)                          AS parcel_count,
               LIST(DISTINCT ps.site_zip)        AS zips
        FROM property_summary ps
        {join_clause}
        WHERE ps.neighborhood_code IS NOT NULL
          AND TRIM(ps.neighborhood_code) <> ''
          AND ps.site_address IS NOT NULL
        GROUP BY ps.neighborhood_code{group_extra}
        HAVING COUNT(*) >= ?
        ORDER BY name
    """, [REGION_MIN_PARCELS]).fetchall()
    return [
        {"region_id": r[0], "name": r[1], "parcel_count": int(r[2]),
         "zips": [z for z in (r[3] or []) if z]}
        for r in rows
    ]


def region_zips(region_id: str, db_path: str | None = None) -> list[str]:
    """Distinct site_zip values a region covers, most-populous first."""
    db_file = db_path or PERMIT_DB_PATH
    if db_exists(db_file):
        con = duckdb.connect(str(db_file), read_only=True)
        try:
            rows = con.execute("""
                SELECT site_zip, COUNT(*) AS n
                FROM property_summary
                WHERE neighborhood_code = ?
                  AND site_zip IS NOT NULL AND TRIM(site_zip) <> ''
                  AND site_address IS NOT NULL
                GROUP BY site_zip
                ORDER BY n DESC
            """, [region_id]).fetchall()
            return [r[0] for r in rows]
        finally:
            con.close()
    return _pg_region_zips(region_id)


def query_properties_for_region(region_id: str, zip_code: str,
                                db_path: str | None = None) -> dict[str, dict]:
    """Parcels for one region within one ZIP, keyed by normalized address.

    Same field set as query_properties(), plus the raw site_address / site_zip /
    mail_city needed to seed the properties table directly from HCAD.
    """
    db_file = db_path or PERMIT_DB_PATH
    if db_exists(db_file):
        con = duckdb.connect(str(db_file), read_only=True)
        try:
            return _duckdb_query_region(con, region_id, zip_code, joined=True)
        except duckdb.CatalogException:
            return _duckdb_query_region(con, region_id, zip_code, joined=False)
        finally:
            con.close()
    return _pg_query_properties_for_region(region_id, zip_code)


def _duckdb_query_region(con, region_id: str, zip_code: str, joined: bool) -> dict[str, dict]:
    name_expr = "nc.dscr" if joined else "NULL::VARCHAR"
    join_clause = "LEFT JOIN neighborhood_codes nc ON nc.cd = ps.neighborhood_code" if joined else ""
    rows = con.execute(f"""
        SELECT
            {_ADDR_NORM_PS} AS address_norm,
            ps.site_address,
            ps.site_zip,
            ps.mail_city,
            TRY_CAST(ps.year_built AS INTEGER)   AS year_built,
            ps.building_sqft                     AS square_footage,
            ps.land_sqft                         AS lot_size,
            ps.tot_appr_val                      AS estimated_value,
            ps.last_sale_date,
            ps.owner_name,
            ps.likely_owner_occupied             AS owner_occupied,
            NULLIF(CONCAT_WS(', ',
                NULLIF(TRIM(ps.mail_addr), ''),
                NULLIF(TRIM(ps.mail_city), ''),
                NULLIF(TRIM(CONCAT_WS(' ', NULLIF(TRIM(ps.mail_state), ''),
                                           NULLIF(TRIM(ps.mail_zip), ''))), '')
            ), '')                               AS mailing_address,
            ps.neighborhood_code,
            {name_expr}                          AS neighborhood_name
        FROM property_summary ps
        {join_clause}
        WHERE ps.neighborhood_code = ?
          AND ps.site_zip = ?
          AND ps.site_address IS NOT NULL
    """, [region_id, zip_code]).fetchall()

    cols = ["address_norm", "site_address", "site_zip", "mail_city", "year_built",
            "square_footage", "lot_size", "estimated_value", "last_sale_date",
            "owner_name", "owner_occupied", "mailing_address",
            "neighborhood_code", "neighborhood_name"]
    result = {}
    for row in rows:
        d = dict(zip(cols, row))
        addr = d.get("address_norm")
        if addr:
            result[addr] = d
    return result


def query_parcels_for_zip(zip_code: str, db_path: str | None = None) -> dict[str, dict]:
    """All parcels in one ZIP, keyed by normalized address, for free HCAD seeding.

    Same field set as query_properties(), plus the raw site_address / site_zip /
    mail_city the seed normalizer (`pipeline.seed._normalize_hcad`) needs to build
    a properties row. Reads the local DuckDB only — zero paid API calls — and
    falls back to the Postgres hcad_* mirror when the DuckDB file is absent.
    """
    db_file = db_path or PERMIT_DB_PATH
    if db_exists(db_file):
        con = duckdb.connect(str(db_file), read_only=True)
        try:
            return _duckdb_query_zip(con, zip_code, joined=True)
        except duckdb.CatalogException:
            return _duckdb_query_zip(con, zip_code, joined=False)
        finally:
            con.close()
    return _pg_query_parcels_for_zip(zip_code)


def _duckdb_query_zip(con, zip_code: str, joined: bool) -> dict[str, dict]:
    name_expr = "nc.dscr" if joined else "NULL::VARCHAR"
    join_clause = "LEFT JOIN neighborhood_codes nc ON nc.cd = ps.neighborhood_code" if joined else ""
    rows = con.execute(f"""
        SELECT
            {_ADDR_NORM_PS} AS address_norm,
            ps.site_address,
            ps.site_zip,
            ps.mail_city,
            TRY_CAST(ps.year_built AS INTEGER)   AS year_built,
            ps.building_sqft                     AS square_footage,
            ps.land_sqft                         AS lot_size,
            ps.tot_appr_val                      AS estimated_value,
            ps.last_sale_date,
            ps.owner_name,
            ps.likely_owner_occupied             AS owner_occupied,
            NULLIF(CONCAT_WS(', ',
                NULLIF(TRIM(ps.mail_addr), ''),
                NULLIF(TRIM(ps.mail_city), ''),
                NULLIF(TRIM(CONCAT_WS(' ', NULLIF(TRIM(ps.mail_state), ''),
                                           NULLIF(TRIM(ps.mail_zip), ''))), '')
            ), '')                               AS mailing_address,
            ps.neighborhood_code,
            {name_expr}                          AS neighborhood_name
        FROM property_summary ps
        {join_clause}
        WHERE ps.site_zip = ?
          AND ps.site_address IS NOT NULL
    """, [zip_code]).fetchall()

    cols = ["address_norm", "site_address", "site_zip", "mail_city", "year_built",
            "square_footage", "lot_size", "estimated_value", "last_sale_date",
            "owner_name", "owner_occupied", "mailing_address",
            "neighborhood_code", "neighborhood_name"]
    result = {}
    for row in rows:
        d = dict(zip(cols, row))
        addr = d.get("address_norm")
        if addr:
            result[addr] = d
    return result


# ── Postgres fallback functions ──────────────────────────────────────────────

def _pg_query_permits(zip_code: str) -> dict[str, int]:
    """Query permit counts from Postgres hcad_* tables."""
    try:
        from pipeline.db import get_conn
        import psycopg2.extras
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT
                    {_ADDR_NORM_HP} AS address_norm,
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


def _pg_query_extra_features(zip_code: str) -> dict[str, dict]:
    """Query pool/slab/garage signals from Postgres hcad_extra_features table."""
    try:
        from pipeline.db import get_conn
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT
                    {_ADDR_NORM_HP} AS address_norm,
                    BOOL_OR(UPPER(ef.l_dscr) LIKE '%%POOL%%')                               AS has_pool,
                    BOOL_OR(UPPER(ef.l_dscr) LIKE '%%CRACKED SLAB%%'
                            OR UPPER(ef.s_dscr) LIKE '%%CRACK%%')                          AS has_cracked_slab,
                    COALESCE(SUM(
                        CASE WHEN UPPER(ef.l_dscr) LIKE '%%GARAGE%%'
                             THEN CAST(NULLIF(ef.units, '') AS INTEGER) ELSE 0 END
                    ), 0)                                                                    AS garage_sqft
                FROM hcad_properties hp
                JOIN hcad_extra_features ef ON ef.acct = hp.acct
                WHERE hp.site_zip = %s
                GROUP BY address_norm
            """, (zip_code,))
            result = {}
            for row in cur.fetchall():
                addr = row[0]
                if addr:
                    result[addr] = {
                        "has_pool":        bool(row[1]),
                        "has_cracked_slab": bool(row[2]),
                        "garage_spaces":   garage_spaces_from_sqft(row[3]),
                    }
        conn.close()
        if result:
            log.info("Postgres HCAD extra_features: %d addresses for ZIP %s", len(result), zip_code)
        return result
    except Exception as e:
        log.debug("Postgres HCAD extra_features query skipped: %s", e)
        return {}


def _pg_query_properties(zip_code: str) -> dict[str, dict]:
    """Query property data from Postgres hcad_* tables."""
    try:
        from pipeline.db import get_conn
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT
                    {_ADDR_NORM} AS address_norm,
                    CAST(NULLIF(year_built, '') AS INTEGER) AS year_built,
                    building_sqft AS square_footage,
                    land_sqft AS lot_size,
                    tot_appr_val AS estimated_value,
                    last_sale_date,
                    owner_name,
                    likely_owner_occupied AS owner_occupied,
                    NULLIF(CONCAT_WS(', ',
                        NULLIF(TRIM(mail_addr), ''),
                        NULLIF(TRIM(mail_city), ''),
                        NULLIF(TRIM(CONCAT_WS(' ', NULLIF(TRIM(mail_state), ''),
                                                   NULLIF(TRIM(mail_zip), ''))), '')
                    ), '') AS mailing_address,
                    neighborhood_code,
                    neighborhood_name
                FROM hcad_properties
                WHERE site_zip = %s AND site_address IS NOT NULL
            """, (zip_code,))
            cols = ["address_norm", "year_built", "square_footage", "lot_size",
                    "estimated_value", "last_sale_date", "owner_name", "owner_occupied",
                    "mailing_address", "neighborhood_code", "neighborhood_name"]
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


def _pg_list_regions() -> list[dict]:
    """Named neighborhoods from the Postgres hcad_properties mirror."""
    try:
        from pipeline.db import get_conn
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT neighborhood_code AS region_id,
                       COALESCE(MAX(neighborhood_name), neighborhood_code) AS name,
                       COUNT(*) AS parcel_count,
                       ARRAY_AGG(DISTINCT site_zip) AS zips
                FROM hcad_properties
                WHERE neighborhood_code IS NOT NULL AND TRIM(neighborhood_code) <> ''
                  AND site_address IS NOT NULL
                GROUP BY neighborhood_code
                HAVING COUNT(*) >= %s
                ORDER BY name
            """, (REGION_MIN_PARCELS,))
            out = [
                {"region_id": r[0], "name": r[1], "parcel_count": int(r[2]),
                 "zips": [z for z in (r[3] or []) if z]}
                for r in cur.fetchall()
            ]
        conn.close()
        return out
    except Exception as e:
        log.warning("Postgres HCAD region list failed: %s", e)
        return []


def _pg_region_zips(region_id: str) -> list[str]:
    try:
        from pipeline.db import get_conn
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT site_zip, COUNT(*) AS n
                FROM hcad_properties
                WHERE neighborhood_code = %s
                  AND site_zip IS NOT NULL AND TRIM(site_zip) <> ''
                  AND site_address IS NOT NULL
                GROUP BY site_zip
                ORDER BY n DESC
            """, (region_id,))
            out = [r[0] for r in cur.fetchall()]
        conn.close()
        return out
    except Exception as e:
        log.warning("Postgres HCAD region zips failed: %s", e)
        return []


def _pg_query_properties_for_region(region_id: str, zip_code: str) -> dict[str, dict]:
    try:
        from pipeline.db import get_conn
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT
                    {_ADDR_NORM} AS address_norm,
                    site_address,
                    site_zip,
                    mail_city,
                    CAST(NULLIF(year_built, '') AS INTEGER) AS year_built,
                    building_sqft AS square_footage,
                    land_sqft AS lot_size,
                    tot_appr_val AS estimated_value,
                    last_sale_date,
                    likely_owner_occupied AS owner_occupied,
                    owner_name,
                    NULLIF(CONCAT_WS(', ',
                        NULLIF(TRIM(mail_addr), ''),
                        NULLIF(TRIM(mail_city), ''),
                        NULLIF(TRIM(CONCAT_WS(' ', NULLIF(TRIM(mail_state), ''),
                                                   NULLIF(TRIM(mail_zip), ''))), '')
                    ), '') AS mailing_address,
                    neighborhood_code,
                    neighborhood_name
                FROM hcad_properties
                WHERE neighborhood_code = %s AND site_zip = %s AND site_address IS NOT NULL
            """, (region_id, zip_code))
            cols = ["address_norm", "site_address", "site_zip", "mail_city", "year_built",
                    "square_footage", "lot_size", "estimated_value", "last_sale_date",
                    "owner_occupied", "owner_name", "mailing_address",
                    "neighborhood_code", "neighborhood_name"]
            result = {}
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                addr = d.get("address_norm")
                if addr:
                    result[addr] = d
        conn.close()
        return result
    except Exception as e:
        log.warning("Postgres HCAD region property query failed: %s", e)
        return {}


def _pg_query_parcels_for_zip(zip_code: str) -> dict[str, dict]:
    """ZIP-level parcel seed from the Postgres hcad_properties mirror."""
    try:
        from pipeline.db import get_conn
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT
                    {_ADDR_NORM} AS address_norm,
                    site_address,
                    site_zip,
                    mail_city,
                    CAST(NULLIF(year_built, '') AS INTEGER) AS year_built,
                    building_sqft AS square_footage,
                    land_sqft AS lot_size,
                    tot_appr_val AS estimated_value,
                    last_sale_date,
                    owner_name,
                    likely_owner_occupied AS owner_occupied,
                    NULLIF(CONCAT_WS(', ',
                        NULLIF(TRIM(mail_addr), ''),
                        NULLIF(TRIM(mail_city), ''),
                        NULLIF(TRIM(CONCAT_WS(' ', NULLIF(TRIM(mail_state), ''),
                                                   NULLIF(TRIM(mail_zip), ''))), '')
                    ), '') AS mailing_address,
                    neighborhood_code,
                    neighborhood_name
                FROM hcad_properties
                WHERE site_zip = %s AND site_address IS NOT NULL
            """, (zip_code,))
            cols = ["address_norm", "site_address", "site_zip", "mail_city", "year_built",
                    "square_footage", "lot_size", "estimated_value", "last_sale_date",
                    "owner_name", "owner_occupied", "mailing_address",
                    "neighborhood_code", "neighborhood_name"]
            result = {}
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                addr = d.get("address_norm")
                if addr:
                    result[addr] = d
        conn.close()
        return result
    except Exception as e:
        log.warning("Postgres HCAD ZIP parcel query failed: %s", e)
        return {}
