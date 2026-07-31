"""
Step 2 — Census ACS enrichment.

Fetches median household income (B19013_001E) for a ZIP and stamps it onto every
property in that ZIP. No API key required for ACS; an optional key removes rate
limits.

Two things this step used to do badly, both measured on ZIP 77449 (41,334
parcels):

  * It requested `for=zip code tabulation area:*` — every ZCTA in the United
    States, ~33,000 rows — and filtered client-side to find the one ZIP it
    wanted. Now it asks for the single ZCTA.

  * It then wrote the resulting integer by pulling every property row into
    Python and upserting them all back, which took 2m24s to store one number.
    Now it is a single UPDATE.
"""
import logging

from config import CENSUS_ACS_URL, CENSUS_API_KEY, CENSUS_INCOME_VAR
from pipeline.db import get_conn
from pipeline.http import get_json

log = logging.getLogger(__name__)


def enrich_census(zip_code: str, account_id: int) -> int:
    """Set zip_median_income for this org's properties in `zip_code`.

    Returns the number of rows updated. Only rows still missing the value are
    touched, so a re-run is cheap and does not churn updated_at.
    """
    income = fetch_income(zip_code)
    if income is None:
        log.info("Census: no median income available for ZIP %s", zip_code)
        return 0

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # One statement. The value is identical for every row in the ZIP, so
            # there is nothing to compute per row and nothing to send over the
            # wire beyond the single integer.
            cur.execute(
                "UPDATE properties SET "
                "  zip_median_income = %s, "
                "  enrichment_flags = COALESCE(enrichment_flags, '{}'::jsonb) "
                "                     || jsonb_build_object('census', 'acs5_2022') "
                "WHERE zip = %s AND account_id = %s "
                "  AND zip_median_income IS DISTINCT FROM %s",
                (income, zip_code, account_id, income),
            )
            n = cur.rowcount
        conn.commit()
    finally:
        conn.close()

    log.info("Census: zip_median_income=%s applied to %d properties in ZIP %s",
             income, n, zip_code)
    return n


def fetch_income(zip_code: str) -> int | None:
    """Median household income for one ZCTA, or None when unavailable.

    Asks for the single ZCTA rather than the national table. The ACS response is
    a header row plus data rows; a missing value comes back as a large negative
    sentinel (-666666666), which int() parses happily, so it is screened out.
    """
    params = {
        "get": CENSUS_INCOME_VAR,
        "for": f"zip code tabulation area:{zip_code}",
    }
    if CENSUS_API_KEY:
        params["key"] = CENSUS_API_KEY

    data = get_json(CENSUS_ACS_URL, params=params, timeout=30)
    return parse_income(data)


def parse_income(data) -> int | None:
    """Pull the income value out of an ACS response. Pure — no HTTP.

    Shape is [[header...], [value, zcta]]. Anything else (empty, error payload,
    unparseable number, negative sentinel) yields None rather than raising: a
    missing income must degrade to an unscored signal, never fail the run.
    """
    if not data or not isinstance(data, list) or len(data) < 2:
        return None
    header, row = data[0], data[1]
    try:
        idx = header.index(CENSUS_INCOME_VAR)
        value = int(row[idx])
    except (ValueError, TypeError, IndexError, AttributeError):
        return None
    # ACS encodes "not available" as a large negative sentinel.
    return value if value >= 0 else None
