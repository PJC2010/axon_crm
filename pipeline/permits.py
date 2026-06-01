"""
Step 5 — Permit activity enrichment.

Queries harris_county.duckdb for 24-month permit counts and writes
permit_count_24mo to the properties table.

Falls back to county adapter registry if the DuckDB is unavailable.
"""
import logging

from pipeline.db import get_conn, fetch_by_zip, upsert_properties
from pipeline import hcad_store

log = logging.getLogger(__name__)


# ── County adapter registry ───────────────────────────────────────────────────
# Map ZIP prefix (first 3 digits) → callable(zip_code) -> {address: count}
COUNTY_ADAPTERS: dict[str, callable] = {}

def register_adapter(zip_prefix: str, fn):
    COUNTY_ADAPTERS[zip_prefix] = fn


# ── Main enrichment function ──────────────────────────────────────────────────

def enrich_permits(zip_code: str, csv_path: str | None = None) -> int:
    if csv_path:
        log.warning(
            "--permit-csv is no longer used; permit data is queried directly "
            "from harris_county.duckdb (PERMIT_DB_PATH in config)."
        )

    if hcad_store.db_exists():
        permit_map = hcad_store.query_permits(zip_code)
    else:
        adapter = COUNTY_ADAPTERS.get(zip_code[:3])
        if adapter:
            permit_map = adapter(zip_code)
        else:
            log.warning(
                "No HCAD DuckDB store found and no county adapter for ZIP %s — "
                "permit_count_24mo will remain NULL.",
                zip_code,
            )
            return 0

    if not permit_map:
        return 0

    conn = get_conn()
    rows = fetch_by_zip(conn, zip_code)
    updates = []
    for row in rows:
        addr_norm = hcad_store.normalize(row["address"])
        count = permit_map.get(addr_norm)
        if count is not None:
            updates.append({
                "address":           row["address"],
                "zip":               zip_code,
                "permit_count_24mo": count,
                "enrichment_flags":  {"permits": "hcad"},
            })

    n = upsert_properties(conn, updates)
    conn.close()
    log.info("Updated permit counts for %d properties in ZIP %s", n, zip_code)
    return n
