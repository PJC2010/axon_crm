"""
Step 4 — Property detail enrichment via RentCast and Attom Data.

RentCast fills: year_built, estimated_value, last_sale_date, last_sale_price,
                estimated_equity, owner_name, owner_occupied, ownership_years.
Attom fills:    garage_spaces, lot_size  (and fills gaps from RentCast).

Attom is ~10x more expensive per record, so it only runs for properties that
are still missing garage_spaces after RentCast.
"""
import logging
import time
from datetime import date

import requests

from config import (
    RENTCAST_API_KEY, RENTCAST_BASE_URL,
    ATTOM_API_KEY, ATTOM_BASE_URL,
)
from pipeline.db import get_conn, fetch_missing_field, upsert_properties

log = logging.getLogger(__name__)


def enrich_property(zip_code: str | None = None) -> int:
    conn = get_conn()
    total = 0

    # RentCast: fill year_built and related fields
    rows = fetch_missing_field(conn, "year_built", zip_code)
    if rows and RENTCAST_API_KEY:
        log.info("RentCast enriching %d properties…", len(rows))
        updates = []
        for row in rows:
            data = _rentcast_detail(row["address"], row.get("zip", ""))
            if data:
                data.update({"address": row["address"], "zip": row["zip"],
                             "enrichment_flags": {"property": "rentcast"}})
                updates.append(data)
            time.sleep(0.05)
        total += upsert_properties(conn, updates)
    elif not RENTCAST_API_KEY:
        log.warning("RENTCAST_API_KEY not set — skipping RentCast property enrichment.")

    # Attom: fill garage_spaces for properties still missing it
    rows_attom = fetch_missing_field(conn, "garage_spaces", zip_code)
    if rows_attom and ATTOM_API_KEY:
        log.info("Attom enriching %d properties for garage data…", len(rows_attom))
        updates = []
        for row in rows_attom:
            data = _attom_detail(row["address"], row.get("zip", ""))
            if data:
                data.update({"address": row["address"], "zip": row["zip"],
                             "enrichment_flags": {"garage": "attom"}})
                updates.append(data)
            time.sleep(0.1)
        total += upsert_properties(conn, updates)
    elif not ATTOM_API_KEY:
        log.warning("ATTOM_API_KEY not set — skipping Attom enrichment.")

    conn.close()
    return total


def _rentcast_detail(address: str, zip_code: str) -> dict | None:
    if not RENTCAST_API_KEY:
        return None
    try:
        resp = requests.get(
            f"{RENTCAST_BASE_URL}/properties",
            headers={"X-Api-Key": RENTCAST_API_KEY},
            params={"address": address, "zipCode": zip_code, "limit": 1},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return None
        p = data[0] if isinstance(data, list) else data

        equity = None
        value = p.get("price")
        if value:
            equity = int(value * 0.6)   # rough 60% equity proxy; replace with real mortgage data if available

        ownership_years = None
        sale_date = p.get("lastSaleDate")
        if sale_date:
            try:
                sold_year = int(sale_date[:4])
                ownership_years = date.today().year - sold_year
            except (ValueError, TypeError):
                pass

        return {
            "year_built":      p.get("yearBuilt"),
            "square_footage":  p.get("squareFootage"),
            "estimated_value": value,
            "estimated_equity": equity,
            "last_sale_date":  sale_date,
            "last_sale_price": p.get("lastSalePrice"),
            "owner_name":      p.get("ownerName"),
            "owner_occupied":  p.get("ownerOccupied"),
            "ownership_years": ownership_years,
        }
    except Exception as e:
        log.warning("RentCast detail failed for %s: %s", address, e)
        return None


def _attom_detail(address: str, zip_code: str) -> dict | None:
    if not ATTOM_API_KEY:
        return None
    try:
        resp = requests.get(
            f"{ATTOM_BASE_URL}/property/detail",
            headers={"apikey": ATTOM_API_KEY, "Accept": "application/json"},
            params={"address1": address, "address2": zip_code},
            timeout=15,
        )
        resp.raise_for_status()
        prop = resp.json().get("property", [{}])[0]
        building = prop.get("building", {})
        lot      = prop.get("lot", {})
        return {
            "garage_spaces": building.get("garageSpaces") or building.get("parkingSpaces"),
            "lot_size":      lot.get("lotSize1"),
            "square_footage": building.get("size", {}).get("livingSize"),
        }
    except Exception as e:
        log.warning("Attom detail failed for %s: %s", address, e)
        return None
