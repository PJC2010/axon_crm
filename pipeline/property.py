"""
Step — Property detail enrichment via RentCast.

Free HCAD runs upstream and fills what it can. This step then fills the
remaining NULL holes from the paid source(s) in PROPERTY_FIELD_SOURCES.
Because upsert_properties only writes non-NULL values, each source touches only
the fields still missing, so paid calls are spent on genuine gaps.
"""
import logging
import time

from config import (
    RENTCAST_API_KEY, RENTCAST_BASE_URL,
    PROPERTY_FIELD_SOURCES, SOURCE_FIELDS,
)
from pipeline.db import get_conn, fetch_missing_any, upsert_properties
from pipeline.equity import estimate_equity
from pipeline.http import get_json

log = logging.getLogger(__name__)

# Per-source detail fetchers and the metadata each one needs.
_SOURCE_CONFIG = {
    "rentcast": {
        "key": RENTCAST_API_KEY,
        "flag": {"property": "rentcast"},
        "delay": 0.05,
        "cap": None,
    },
}


def enrich_property(zip_code: str, account_id: int, selected_only: bool = False) -> dict:
    """Run each configured source in priority order.

    When `selected_only` is True (capped/radius runs), only rows the selection
    step marked enrichment_selected = TRUE are enriched, keeping paid calls
    bounded to the chosen subset.

    Returns per-source counters: {source: {"ok", "fail", "updated",
    "skipped_no_key"}}.
    """
    conn = get_conn()
    counters: dict[str, dict] = {}
    fetchers = {"rentcast": _rentcast_detail}

    try:
        for source in PROPERTY_FIELD_SOURCES:
            cfg = _SOURCE_CONFIG[source]
            counter = {"ok": 0, "fail": 0, "updated": 0, "skipped_no_key": False}
            counters[source] = counter

            if not cfg["key"]:
                counter["skipped_no_key"] = True
                log.warning("%s key not set — skipping %s property enrichment.",
                            source.upper(), source)
                continue

            rows = fetch_missing_any(conn, SOURCE_FIELDS[source], account_id, zip_code,
                                     selected_only=selected_only)
            if cfg["cap"]:
                rows = rows[: cfg["cap"]]
            if not rows:
                continue

            log.info("%s enriching %d properties…", source, len(rows))
            updates = []
            for row in rows:
                data = fetchers[source](row["address"], row.get("zip", ""))
                if data:
                    counter["ok"] += 1
                    data.update({"address": row["address"], "zip": row["zip"],
                                 "enrichment_flags": cfg["flag"]})
                    updates.append(data)
                else:
                    counter["fail"] += 1
                time.sleep(cfg["delay"])
            counter["updated"] = upsert_properties(conn, updates, account_id)
    finally:
        conn.close()

    return counters


def _rentcast_detail(address: str, zip_code: str) -> dict | None:
    data = get_json(
        f"{RENTCAST_BASE_URL}/properties",
        headers={"X-Api-Key": RENTCAST_API_KEY},
        params={"address": address, "zipCode": zip_code, "limit": 1},
        timeout=15,
    )
    if not data:
        return None
    p = data[0] if isinstance(data, list) else data

    value = p.get("price")
    sale_date = p.get("lastSaleDate")
    sale_price = p.get("lastSalePrice")

    ownership_years = None
    if sale_date:
        try:
            ownership_years = _years_from(sale_date)
        except (ValueError, TypeError):
            pass

    # Garage data lives in the nested `features` object; owner name lives in the
    # nested `owner.names` list (NOT a flat `ownerName` field — confirmed live).
    features = p.get("features") or {}
    owner = p.get("owner") or {}
    owner_names = owner.get("names")
    owner_name = (owner_names[0] if isinstance(owner_names, list) and owner_names
                  else p.get("ownerName"))

    return {
        "year_built":       p.get("yearBuilt"),
        "square_footage":   p.get("squareFootage"),
        "estimated_value":  value,
        "estimated_equity": estimate_equity(value, sale_price, sale_date),
        "last_sale_date":   sale_date,
        "last_sale_price":  sale_price,
        "owner_name":       owner_name,
        "owner_occupied":   p.get("ownerOccupied"),
        "ownership_years":  ownership_years,
        "garage_spaces":    features.get("garageSpaces"),
        "garage_type":      features.get("garageType"),
    }


def _years_from(sale_date: str) -> int:
    from datetime import date
    return date.today().year - int(str(sale_date)[:4])
