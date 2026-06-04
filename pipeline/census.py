"""
Step 2 — Census ACS enrichment.

Fetches median household income (B19013_001E) for each unique ZIP code
in the properties table that is missing zip_median_income.
No API key required for ACS; optional key removes rate limits.
"""
import logging

from config import CENSUS_ACS_URL, CENSUS_API_KEY, CENSUS_INCOME_VAR
from pipeline.db import get_conn, fetch_missing_field, upsert_properties
from pipeline.http import get_json

log = logging.getLogger(__name__)


def enrich_census(zip_code: str | None = None) -> int:
    conn = get_conn()
    rows = fetch_missing_field(conn, "zip_median_income", zip_code)

    # De-duplicate: only hit the API once per ZIP
    zips = list({r["zip"] for r in rows if r.get("zip")})
    if not zips:
        log.info("No properties need census enrichment.")
        conn.close()
        return 0

    income_by_zip = _fetch_income(zips)
    log.info("Census returned income data for %d ZIPs", len(income_by_zip))

    updates = []
    for row in rows:
        z = row.get("zip")
        income = income_by_zip.get(z)
        if income is not None:
            updates.append({
                "address": row["address"],
                "zip":     z,
                "zip_median_income": income,
                "enrichment_flags": {"census": "acs5_2022"},
            })

    n = upsert_properties(conn, updates)
    conn.close()
    log.info("Updated zip_median_income for %d properties", n)
    return n


def _fetch_income(zips: list[str]) -> dict[str, int]:
    """Return {zip: median_income} for the given ZIP list."""
    params = {
        "get": f"NAME,{CENSUS_INCOME_VAR}",
        "for": "zip code tabulation area:*",
    }
    if CENSUS_API_KEY:
        params["key"] = CENSUS_API_KEY

    data = get_json(CENSUS_ACS_URL, params=params, timeout=30)
    if not data:
        return {}

    zip_set = set(zips)
    result = {}
    header = data[0]
    zcta_idx = header.index("zip code tabulation area")
    inc_idx  = header.index(CENSUS_INCOME_VAR)

    for row in data[1:]:
        zcta = row[zcta_idx]
        if zcta in zip_set:
            try:
                result[zcta] = int(row[inc_idx])
            except (ValueError, TypeError):
                pass   # -666666666 = not available
    return result
