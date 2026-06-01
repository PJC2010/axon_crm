"""
Step 4b — Harris County Appraisal District fallback enrichment.

Backfills null property fields using harris_county.duckdb when RentCast
and Attom return nothing. Never overwrites a value that's already set.

Fields backfilled (if null):
  year_built, square_footage, lot_size, estimated_value,
  last_sale_date, owner_name, owner_occupied, ownership_years
"""
import logging
from datetime import date

from pipeline.db import get_conn, fetch_by_zip, upsert_properties
from pipeline import hcad_store

log = logging.getLogger(__name__)


def enrich_hcad(zip_code: str) -> int:
    if not hcad_store.db_exists():
        log.info("[4b] HCAD: DuckDB not found, skipping")
        return 0

    hcad_map = hcad_store.query_properties(zip_code)
    if not hcad_map:
        log.info("[4b] HCAD: no data for ZIP %s", zip_code)
        return 0

    conn = get_conn()
    rows = fetch_by_zip(conn, zip_code)
    updates = []

    for row in rows:
        addr_norm = hcad_store.normalize(row["address"])
        hcad = hcad_map.get(addr_norm)
        if not hcad:
            continue

        update: dict = {"address": row["address"], "zip": zip_code}
        changed = False

        def _backfill(our_field: str, hcad_field: str, hcad_val):
            nonlocal changed
            if row.get(our_field) is None and hcad_val is not None:
                update[our_field] = hcad_val
                changed = True

        _backfill("year_built",      "year_built",      hcad.get("year_built"))
        _backfill("square_footage",  "square_footage",  hcad.get("square_footage"))
        _backfill("lot_size",        "lot_size",        hcad.get("lot_size"))
        _backfill("estimated_value", "estimated_value", hcad.get("estimated_value"))
        _backfill("last_sale_date",  "last_sale_date",  hcad.get("last_sale_date"))
        _backfill("owner_name",      "owner_name",      hcad.get("owner_name"))
        _backfill("owner_occupied",  "owner_occupied",  hcad.get("owner_occupied"))

        # Derive ownership_years from last_sale_date if not already set
        if row.get("ownership_years") is None:
            sale_date = update.get("last_sale_date") or hcad.get("last_sale_date")
            if isinstance(sale_date, date):
                years = (date.today() - sale_date).days // 365
                update["ownership_years"] = years
                changed = True

        if changed:
            update["enrichment_flags"] = {"hcad": "assessor"}
            updates.append(update)

    n = upsert_properties(conn, updates)
    conn.close()
    log.info("[4b] HCAD: backfilled %d properties in ZIP %s", n, zip_code)
    return n
