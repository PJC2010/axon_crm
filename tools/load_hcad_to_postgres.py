#!/usr/bin/env python3
"""
Bulk-load the whole Harris County HCAD dataset from the local DuckDB into a
Postgres database (e.g. Render's managed Postgres).

Render's filesystem is ephemeral, so the multi-GB harris_county.duckdb cannot
live on the server. Instead, build the DuckDB locally and mirror it into the
durable Postgres `hcad_*` tables, which pipeline/hcad_store.py reads via its
Postgres fallback when no DuckDB file is present.

This is the whole-county counterpart to the per-ZIP `tools/export_hcad_zip.py`
→ `POST /api/hcad/upload` flow. It loads all three tables the pipeline uses,
including the neighborhood names and extra-features (pool/slab/garage) that the
per-ZIP path omits, so the Postgres path matches the DuckDB path.

Prerequisites:
  1. Build the DuckDB first (see tools/build_hcad_duckdb.py).
  2. Run migrations on the target DB so the hcad_* tables exist
     (`python db/migrate.py`).

Usage:
    # Loads from PERMIT_DB_PATH into DATABASE_URL by default:
    python tools/load_hcad_to_postgres.py

    # Explicit source/target (use Render's EXTERNAL database URL):
    python tools/load_hcad_to_postgres.py \
        --duckdb /path/to/harris_county.duckdb \
        --dsn "postgresql://user:pass@host:5432/dbname"
"""
import argparse
import os
import sys
import tempfile
from pathlib import Path

import duckdb
import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import PERMIT_DB_PATH  # noqa: E402


# (postgres table, postgres columns, duckdb SELECT). Each SELECT is run only if
# its source table exists in the DuckDB; columns are written in this exact order.
def _table_specs(duckdb_tables: set[str]) -> list[tuple[str, str, str]]:
    has_nbhd = "neighborhood_codes" in duckdb_tables
    nbhd_name = "nc.dscr" if has_nbhd else "NULL"
    nbhd_join = ("LEFT JOIN neighborhood_codes nc ON nc.cd = ps.neighborhood_code"
                 if has_nbhd else "")

    specs = [(
        "hcad_properties",
        "acct, site_address, site_zip, year_built, building_sqft, land_sqft, "
        "tot_appr_val, last_sale_date, owner_name, likely_owner_occupied, "
        "mail_addr, mail_city, mail_state, mail_zip, neighborhood_code, neighborhood_name",
        f"""
        SELECT ps.acct, ps.site_address, ps.site_zip, ps.year_built, ps.building_sqft,
               ps.land_sqft, ps.tot_appr_val, ps.last_sale_date, ps.owner_name,
               ps.likely_owner_occupied, ps.mail_addr, ps.mail_city, ps.mail_state,
               ps.mail_zip, ps.neighborhood_code, {nbhd_name} AS neighborhood_name
        FROM property_summary ps
        {nbhd_join}
        WHERE ps.site_address IS NOT NULL
        """,
    )]

    if "permits" in duckdb_tables:
        specs.append((
            "hcad_permits",
            "acct, permit_id, status, issue_date, permit_type, description",
            """
            SELECT acct, id AS permit_id,
                   ANY_VALUE(status)         AS status,
                   ANY_VALUE(issue_date)     AS issue_date,
                   ANY_VALUE(permit_type)    AS permit_type,
                   ANY_VALUE(permit_tp_descr) AS description
            FROM permits
            WHERE id IS NOT NULL
            GROUP BY acct, id
            """,
        ))

    if "extra_features" in duckdb_tables:
        specs.append((
            "hcad_extra_features",
            "acct, bld_num, cd, s_dscr, l_dscr, units",
            """
            SELECT acct,
                   COALESCE(bld_num, '') AS bld_num,
                   COALESCE(cd, '')      AS cd,
                   ANY_VALUE(s_dscr)     AS s_dscr,
                   ANY_VALUE(l_dscr)     AS l_dscr,
                   ANY_VALUE(uts)        AS units
            FROM extra_features
            GROUP BY acct, COALESCE(bld_num, ''), COALESCE(cd, '')
            """,
        ))

    return specs


def _pg_table_exists(cur, table: str) -> bool:
    cur.execute("SELECT to_regclass(%s)", (table,))
    return cur.fetchone()[0] is not None


def load(duckdb_path: str, dsn: str) -> None:
    if not Path(duckdb_path).exists():
        sys.exit(f"error: DuckDB not found at {duckdb_path} — build it first with "
                 f"tools/build_hcad_duckdb.py")

    con = duckdb.connect(duckdb_path, read_only=True)
    duckdb_tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    if "property_summary" not in duckdb_tables:
        sys.exit("error: DuckDB has no property_summary table — rebuild it.")

    pg = psycopg2.connect(dsn)
    try:
        with pg.cursor() as cur:
            specs = _table_specs(duckdb_tables)
            for table, _cols, _q in specs:
                if not _pg_table_exists(cur, table):
                    sys.exit(f"error: target table {table} is missing — run "
                             f"`python db/migrate.py` against this database first.")

            for table, cols, query in specs:
                print(f"Loading {table} ...", flush=True)
                # DuckDB writes the query result to a temp CSV; psycopg2 streams it
                # into Postgres via COPY (fast bulk path for ~1.5M parcels).
                with tempfile.NamedTemporaryFile(suffix=".csv") as tmp:
                    con.execute(
                        f"COPY ({query}) TO '{tmp.name}' (FORMAT CSV, HEADER TRUE)"
                    )
                    cur.execute(f"TRUNCATE {table}")
                    with open(tmp.name, "r", encoding="utf-8") as fh:
                        cur.copy_expert(
                            f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT CSV, HEADER TRUE)",
                            fh,
                        )
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                print(f"  {table}: {cur.fetchone()[0]:,} rows", flush=True)
        pg.commit()
    finally:
        pg.close()
        con.close()
    print("\nDone. The Postgres hcad_* mirror is loaded.")


def main() -> None:
    p = argparse.ArgumentParser(description="Bulk-load HCAD DuckDB into Postgres")
    p.add_argument("--duckdb", default=str(PERMIT_DB_PATH),
                   help=f"Source DuckDB path (default: {PERMIT_DB_PATH})")
    p.add_argument("--dsn", default=os.getenv("DATABASE_URL"),
                   help="Target Postgres DSN (default: $DATABASE_URL). Use Render's "
                        "EXTERNAL database URL when loading from your machine.")
    args = p.parse_args()
    if not args.dsn:
        p.error("no target database: pass --dsn or set DATABASE_URL")
    load(args.duckdb, args.dsn)


if __name__ == "__main__":
    main()
