"""
Step — Property detail enrichment via RentCast and Attom Data.

Free HCAD runs upstream and fills what it can. This step then fills the
remaining NULL holes from paid sources in priority order (RentCast, then Attom).
Because upsert_properties only writes non-NULL values, each source touches only
the fields still missing, so paid calls are spent on genuine gaps.

RentCast and Attom both return value/sale/owner/year fields; Attom additionally
provides garage and lot data. Attom is ~10x more expensive, so it runs second
and is capped per ZIP (ATTOM_MAX_ROWS_PER_ZIP).
"""
import logging
import time

from config import (
    RENTCAST_API_KEY, RENTCAST_BASE_URL,
    ATTOM_API_KEY, ATTOM_BASE_URL,
    PROPERTY_FIELD_SOURCES, SOURCE_FIELDS, ATTOM_MAX_ROWS_PER_ZIP,
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
    "attom": {
        "key": ATTOM_API_KEY,
        "flag": {"property": "attom"},
        "delay": 0.1,
        "cap": ATTOM_MAX_ROWS_PER_ZIP,
    },
}


def enrich_property(zip_code: str | None = None, selected_only: bool = False) -> dict:
    """Run each configured source in priority order.

    When `selected_only` is True (capped/radius runs), only rows the selection
    step marked enrichment_selected = TRUE are enriched, keeping paid calls
    bounded to the chosen subset.

    Returns per-source counters: {source: {"ok", "fail", "updated",
    "skipped_no_key"}}.
    """
    conn = get_conn()
    counters: dict[str, dict] = {}
    fetchers = {"rentcast": _rentcast_detail, "attom": _attom_detail}

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

            rows = fetch_missing_any(conn, SOURCE_FIELDS[source], zip_code,
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
            counter["updated"] = upsert_properties(conn, updates)
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

    return {
        "year_built":       p.get("yearBuilt"),
        "square_footage":   p.get("squareFootage"),
        "estimated_value":  value,
        "estimated_equity": estimate_equity(value, sale_price, sale_date),
        "last_sale_date":   sale_date,
        "last_sale_price":  sale_price,
        "owner_name":       p.get("ownerName"),
        "owner_occupied":   p.get("ownerOccupied"),
        "ownership_years":  ownership_years,
    }


def _attom_detail(address: str, zip_code: str) -> dict | None:
    payload = get_json(
        f"{ATTOM_BASE_URL}/assessment/detail",
        headers={"apikey": ATTOM_API_KEY, "Accept": "application/json"},
        params={"address1": address, "address2": zip_code},
        timeout=15,
    )
    if not payload:
        return None
    props = payload.get("property") or [{}]
    prop = props[0] if props else {}

    building   = prop.get("building", {}) or {}
    lot        = prop.get("lot", {}) or {}
    summary    = prop.get("summary", {}) or {}
    assessment = prop.get("assessment", {}) or {}
    parking    = building.get("parking", {}) or {}

    # ── Garage ────────────────────────────────────────────────────────────────
    garage_type = parking.get("garageType") or ""
    prkg_type   = (parking.get("prkgType") or "").lower()
    prkg_size   = parking.get("prkgSize")
    is_garage   = bool(garage_type) or "garage" in prkg_type
    garage_spaces = None
    if is_garage:
        try:
            sqft = float(prkg_size) if prkg_size is not None else 0
            garage_spaces = 3 if sqft >= 550 else 2 if sqft >= 300 else 1
        except (ValueError, TypeError):
            garage_spaces = 1

    # ── Value / sale / owner (previously discarded) ───────────────────────────
    assessed = assessment.get("assessed", {}) or {}
    market   = assessment.get("market", {}) or {}
    sale     = assessment.get("sale", {}) or {}
    owner    = assessment.get("owner", {}) or {}
    mortgage = assessment.get("mortgage", {}) or {}

    estimated_value = assessed.get("assdttlvalue") or market.get("mktttlvalue")
    sale_amount = (sale.get("amount", {}) or {}).get("saleamt")
    sale_date = sale.get("salesearchdate") or sale.get("saledate")
    owner_name = ((owner.get("owner1", {}) or {}).get("fullname")
                  or owner.get("owner1"))
    absentee = (owner.get("absenteeownerstatus") or "").upper()
    owner_occupied = (absentee == "O") if absentee in ("O", "A") else None
    mortgage_balance = (mortgage.get("lender", {}) or {}).get("balance")

    return {
        "year_built":       summary.get("yearbuilt"),
        "square_footage":   (building.get("size", {}) or {}).get("livingsize"),
        "lot_size":         lot.get("lotsize2"),
        "estimated_value":  estimated_value,
        "estimated_equity": estimate_equity(estimated_value, sale_amount, sale_date,
                                             mortgage_balance=mortgage_balance),
        "last_sale_date":   sale_date,
        "last_sale_price":  sale_amount,
        "owner_name":       owner_name,
        "owner_occupied":   owner_occupied,
        "garage_spaces":    garage_spaces,
        "garage_type":      garage_type or None,
    }


def _years_from(sale_date: str) -> int:
    from datetime import date
    return date.today().year - int(str(sale_date)[:4])
