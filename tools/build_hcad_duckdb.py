#!/usr/bin/env python3
"""
Build harris_county.duckdb from raw HCAD "Real property" text files.

The pipeline (pipeline/hcad_store.py) reads three tables out of this DuckDB:

    property_summary   one row per parcel — address, value, owner, mailing addr
    permits            building permits, joined to property_summary by acct
    extra_features     pool / cracked-slab / garage signals (optional)

This tool maps the raw, tab-delimited HCAD export files onto those tables. It is
the missing "load" half of the HCAD integration: tools/export_hcad_zip.py reads
*out* of this DuckDB to push per-ZIP CSVs to Postgres, but nothing in the repo
built the DuckDB in the first place. Run this once after downloading the HCAD
"Real and Personal Property Data" export, then point PERMIT_DB_PATH at the
result (or run export_hcad_zip.py to mirror selected ZIPs into Postgres).

Source files (HCAD PDATA, https://hcad.org/pdata/) and the table each feeds:

    Real_acct_owner.zip
      real_acct.txt   -> property_summary   (site + mailing address, value, area)
      owners.txt      -> property_summary   (clean owner name, primary owner)
      deeds.txt       -> property_summary   (last_sale_date = latest deed)
      permits.txt     -> permits
    Real_building_land.zip   (optional — enables pool/slab + true year-built)
      extra_features.txt -> extra_features
      building_res.txt   -> property_summary (year_built override = date_erected)

If the optional files are absent the corresponding columns degrade gracefully:
year_built falls back to real_acct.yr_impr (Parcel Year Improved) and the
extra_features table is simply not created (pool/slab signals stay empty).

Column meanings come from the HCAD PDATA Codebook
(https://hcad.org/assets/uploads/pdf/pdataCodebook.pdf).

Usage:
    python tools/build_hcad_duckdb.py /path/to/unzipped_hcad_dir
    python tools/build_hcad_duckdb.py /path/to/dir -o harris_county.duckdb
    python tools/build_hcad_duckdb.py /path/to/dir --encoding latin-1

The HCAD files are tab-delimited with a header row. They are encoded
Windows-1252 (cp1252), not UTF-8, which is the default here. Note: DuckDB's
"latin-1" reader rejects some real HCAD bytes (e.g. 0xA5), so cp1252 — not
latin-1 — is the correct encoding for these files.
"""
import argparse
import sys
from pathlib import Path

import duckdb

# Repo root on sys.path so we can read config.PERMIT_DB_PATH for the default out.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from config import PERMIT_DB_PATH as DEFAULT_DB  # noqa: E402
except Exception:  # config may require env vars we don't have here
    DEFAULT_DB = "harris_county.duckdb"


def _src(con: duckdb.DuckDBPyConnection, path: Path, encoding: str) -> str:
    """A read_csv(...) clause for one HCAD text file, or '' if it is missing.

    Column names are taken verbatim from the header row (HCAD headers are already
    lowercase, and DuckDB identifiers are case-insensitive). all_varchar avoids
    type-sniffing surprises on 80-column rows; ignore_errors skips the occasional
    malformed line rather than aborting.
    """
    if not path.exists():
        return ""
    return (
        f"read_csv('{path.as_posix()}', delim='\t', header=true, "
        f"quote='', escape='', all_varchar=true, "
        f"ignore_errors=true, encoding='{encoding}')"
    )


def _has_column(con: duckdb.DuckDBPyConnection, src: str, column: str) -> bool:
    """True when the read_csv clause `src` exposes `column`.

    HCAD's header row is the schema, and it varies between exports and between
    the full download and the trimmed extracts used in testing. DuckDB
    identifiers are case-insensitive, so the comparison is folded.
    """
    if not src:
        return False
    try:
        names = con.execute(f"SELECT * FROM {src} LIMIT 0").description or []
    except Exception:
        return False
    return column.lower() in {str(d[0]).lower() for d in names}


def build(src_dir: Path, out_db: Path, encoding: str) -> None:
    f = {name: src_dir / f"{name}.txt" for name in
         ("real_acct", "owners", "deeds", "permits", "extra_features", "building_res",
          "real_neighborhood_code")}

    real_acct = None  # set below; required
    if out_db.exists():
        out_db.unlink()
    con = duckdb.connect(str(out_db))

    real_src = _src(con, f["real_acct"], encoding)
    if not real_src:
        sys.exit(f"error: {f['real_acct']} not found (real_acct.txt is required)")
    real_acct = real_src

    # ── helper subqueries for optional joins ────────────────────────────────
    # NOTE: real_acct.acct is space-padded to a fixed width, while deeds/owners/
    # building_res/permits/extra_features store acct UNpadded. Every acct key is
    # therefore TRIM()'d so the joins below (and the runtime ps.acct = *.acct
    # joins in pipeline/hcad_store.py) actually match.
    deeds_src = _src(con, f["deeds"], encoding)
    last_sale = (
        f"(SELECT TRIM(acct) AS acct, MAX(TRY_STRPTIME(dos, '%m/%d/%Y')::DATE) AS last_sale_date "
        f"FROM {deeds_src} WHERE dos IS NOT NULL GROUP BY TRIM(acct))"
    ) if deeds_src else "(SELECT NULL::VARCHAR AS acct, NULL::DATE AS last_sale_date WHERE FALSE)"

    owners_src = _src(con, f["owners"], encoding)
    owner = (
        f'(SELECT TRIM(acct) AS acct, ANY_VALUE("name") AS owner_name FROM {owners_src} '
        f"WHERE COALESCE(ln_num, '1') = '1' GROUP BY TRIM(acct))"
    ) if owners_src else "(SELECT NULL::VARCHAR AS acct, NULL::VARCHAR AS owner_name WHERE FALSE)"

    bres_src = _src(con, f["building_res"], encoding)
    byear = (
        f"(SELECT TRIM(acct) AS acct, MIN(TRY_CAST(NULLIF(date_erected, '') AS INTEGER)) AS year_built "
        f"FROM {bres_src} GROUP BY TRIM(acct))"
    ) if bres_src else "(SELECT NULL::VARCHAR AS acct, NULL::INTEGER AS year_built WHERE FALSE)"

    # The Texas Comptroller State Category Code — A* single-family, B* multi-
    # family, C* vacant, F1/F2 commercial/industrial, J* utility, X* exempt. The
    # county's own answer to "is this a house?", which pipeline/residential.py
    # uses as its strongest signal.
    #
    # Probed rather than assumed: `_src` reads every column of whatever header
    # the export carries, and older HCAD exports (and the trimmed files people
    # test with) do not all have this one. Naming a missing column would abort
    # the whole build, so it degrades to NULL instead — the same
    # degrade-gracefully rule the pipeline's optional steps follow.
    has_state_class = _has_column(con, real_acct, "state_class")
    state_class_expr = (
        "NULLIF(TRIM(ra.state_class), '')" if has_state_class else "NULL::VARCHAR"
    )
    if not has_state_class:
        print("  note: real_acct.txt has no state_class column — "
              "non-residential filtering will fall back to heuristics")

    # The parcel's own city (site_addr_2 — see docs/hcad_real_property_mapping.md).
    # This is the SITUS city, distinct from the owner's mail_city: dropping it
    # here is what once made the seed "fall back" to the owner's mailing city,
    # so an absentee owner in Lake Dallas put "LAKE DALLAS" on a Houston lead.
    has_site_city = _has_column(con, real_acct, "site_addr_2")
    site_city_expr = (
        "NULLIF(TRIM(ra.site_addr_2), '')" if has_site_city else "NULL::VARCHAR"
    )
    if not has_site_city:
        print("  note: real_acct.txt has no site_addr_2 column — "
              "site_city will be NULL (leads display without a city)")

    # ── property_summary ────────────────────────────────────────────────────
    # owner_occupied heuristic: the owner's mailing street line matches the
    # parcel's site street line (same normalization the pipeline uses for
    # address matching — lowercase, alphanumerics + spaces, collapsed).
    print("Building property_summary ...")
    con.execute(f"""
        CREATE TABLE property_summary AS
        WITH ra AS (SELECT * REPLACE (TRIM(acct) AS acct) FROM {real_acct}),
             ls AS {last_sale},
             ow AS {owner},
             yb AS {byear},
        norm AS (
            SELECT
                ra.acct,
                NULLIF(TRIM(ra.site_addr_1), '')                       AS site_address,
                {site_city_expr}                                       AS site_city,
                NULLIF(TRIM(ra.site_addr_3), '')                       AS site_zip,
                COALESCE(yb.year_built,
                         TRY_CAST(NULLIF(ra.yr_impr, '') AS INTEGER))  AS year_built,
                TRY_CAST(NULLIF(ra.bld_ar, '')  AS BIGINT)            AS building_sqft,
                TRY_CAST(NULLIF(ra.land_ar, '') AS BIGINT)            AS land_sqft,
                TRY_CAST(NULLIF(ra.tot_appr_val, '') AS BIGINT)       AS tot_appr_val,
                ls.last_sale_date                                     AS last_sale_date,
                COALESCE(ow.owner_name, NULLIF(TRIM(ra.mailto), ''))  AS owner_name,
                NULLIF(TRIM(ra.mail_addr_1), '')                      AS mail_addr,
                NULLIF(TRIM(ra.mail_city), '')                        AS mail_city,
                NULLIF(TRIM(ra.mail_state), '')                       AS mail_state,
                NULLIF(TRIM(ra.mail_zip), '')                         AS mail_zip,
                {state_class_expr}                                     AS state_class,
                NULLIF(TRIM(ra.Neighborhood_Code), '')                AS neighborhood_code,
                NULLIF(TRIM(ra.Neighborhood_Grp), '')                 AS neighborhood_grp,
                LOWER(REGEXP_REPLACE(COALESCE(ra.site_addr_1, ''), '[^a-z0-9 ]', '', 'g')) AS site_norm,
                LOWER(REGEXP_REPLACE(COALESCE(ra.mail_addr_1, ''), '[^a-z0-9 ]', '', 'g')) AS mail_norm
            FROM ra
            LEFT JOIN ls ON ls.acct = ra.acct
            LEFT JOIN ow ON ow.acct = ra.acct
            LEFT JOIN yb ON yb.acct = ra.acct
        )
        SELECT
            acct, site_address, site_city, site_zip, year_built, building_sqft, land_sqft,
            tot_appr_val, last_sale_date, owner_name,
            mail_addr, mail_city, mail_state, mail_zip,
            state_class, neighborhood_code, neighborhood_grp,
            (site_norm <> '' AND TRIM(site_norm) = TRIM(mail_norm)) AS likely_owner_occupied
        FROM norm
    """)

    # ── permits ─────────────────────────────────────────────────────────────
    permits_src = _src(con, f["permits"], encoding)
    if permits_src:
        print("Building permits ...")
        con.execute(f"""
            CREATE TABLE permits AS
            SELECT
                TRY_CAST(NULLIF(id, '') AS BIGINT)        AS id,
                TRIM(acct)                                AS acct,
                status,
                TRY_STRPTIME(issue_date, '%m/%d/%Y')::DATE AS issue_date,
                permit_type,
                permit_tp_descr
            FROM {permits_src}
            WHERE id IS NOT NULL
        """)
    else:
        print("  (permits.txt absent — skipping permits table)")

    # ── extra_features (optional: pool / slab / garage) ─────────────────────
    ef_src = _src(con, f["extra_features"], encoding)
    if ef_src:
        print("Building extra_features ...")
        con.execute(f"""
            CREATE TABLE extra_features AS
            SELECT TRIM(acct) AS acct, bld_num, cd, s_dscr, l_dscr, uts
            FROM {ef_src}
        """)
    else:
        print("  (extra_features.txt absent — pool/slab/garage signals will be empty)")

    # ── neighborhood_codes lookup (optional) ────────────────────────────────
    nc_src = _src(con, f["real_neighborhood_code"], encoding)
    if nc_src:
        print("Building neighborhood_codes ...")
        con.execute(f"""
            CREATE TABLE neighborhood_codes AS
            SELECT
                NULLIF(TRIM(cd), '')   AS cd,
                NULLIF(TRIM(dscr), '') AS dscr
            FROM {nc_src}
            WHERE cd IS NOT NULL AND TRIM(cd) <> ''
        """)
    else:
        print("  (real_neighborhood_code.txt absent — neighborhood names will be empty)")

    # ── indexes + report ────────────────────────────────────────────────────
    con.execute("CREATE INDEX idx_ps_zip ON property_summary(site_zip)")
    con.execute("CREATE INDEX idx_ps_acct ON property_summary(acct)")
    tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    if "permits" in tables:
        con.execute("CREATE INDEX idx_pm_acct ON permits(acct)")
    if "extra_features" in tables:
        con.execute("CREATE INDEX idx_ef_acct ON extra_features(acct)")
    if "neighborhood_codes" in tables:
        con.execute("CREATE INDEX idx_nc_cd ON neighborhood_codes(cd)")

    print("\nDone. Row counts:")
    for t in tables:
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:<18} {n:>12,}")
    occ = con.execute(
        "SELECT COUNT(*) FILTER (WHERE likely_owner_occupied), COUNT(*) FROM property_summary"
    ).fetchone()
    print(f"\n  owner-occupied: {occ[0]:,} / {occ[1]:,}")
    print(f"  written to: {out_db}")
    con.close()


def main() -> None:
    p = argparse.ArgumentParser(description="Build harris_county.duckdb from raw HCAD real-property files")
    p.add_argument("src_dir", help="Directory of unzipped HCAD .txt files")
    p.add_argument("-o", "--out", default=str(DEFAULT_DB), help=f"Output DuckDB path (default: {DEFAULT_DB})")
    p.add_argument("--encoding", default="cp1252", help="Source file encoding (default: cp1252)")
    args = p.parse_args()

    src_dir = Path(args.src_dir)
    if not src_dir.is_dir():
        sys.exit(f"error: {src_dir} is not a directory")
    build(src_dir, Path(args.out), args.encoding)


if __name__ == "__main__":
    main()
