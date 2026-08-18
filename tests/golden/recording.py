"""Live vendor fetchers — shared by scripts/refresh_fixtures.py (recording)
and test_vendor_contract.py (the nightly Layer B contract run), so a payload
is always recorded and drift-checked through the same request shape.

Every fetcher returns ``(payload, skip_reason)``: payload is the raw,
UNSANITIZED vendor response (sanitize before anything touches disk!), and
skip_reason is a human-readable string when the source can't be asked at all
(no key, no county database) — "can't ask" must stay distinguishable from
"asked, vendor said nothing".

Request shapes deliberately mirror the production callers (noted per
function); if production changes how it calls a vendor, change it here too or
the contract run measures a request nobody makes anymore.
"""
import datetime

import config
from pipeline import hcad_store
from pipeline.http import get_json, get_json_result


def fetch_rentcast(address: str, zip_code: str, state: str = "TX"):
    """Mirrors pipeline/property.py::_rentcast_detail's request exactly."""
    if not config.RENTCAST_API_KEY:
        return None, "RENTCAST_API_KEY not set"
    data, answered = get_json_result(
        f"{config.RENTCAST_BASE_URL}/properties",
        headers={"X-Api-Key": config.RENTCAST_API_KEY},
        params={"address": address, "zipCode": zip_code, "limit": 1,
                "state": state},
        timeout=15,
    )
    if not answered:
        return None, "RentCast unreachable"
    # An answered no-record is a real, recordable fact: the empty list.
    return (data if data else []), None


def fetch_acs(zip_code: str):
    """Mirrors pipeline/census.py::fetch_income's request shape — minus the
    optional CENSUS_API_KEY. Deliberate: the key travels as a `key=` QUERY
    param, and a requests connection error embeds the full URL (query string
    included) in its message, which pipeline/http.py logs — from the nightly
    job that log tail is posted into a public-to-the-repo GitHub issue. ACS
    works keyless at this volume (~25 lookups/night); a recording/contract
    run never needs to put the key on that path."""
    params = {"get": config.CENSUS_INCOME_VAR,
              "for": f"zip code tabulation area:{zip_code}"}
    data = get_json(config.CENSUS_ACS_URL, params=params, timeout=30)
    if data is None:
        return None, "ACS unreachable"
    return data, None


def fetch_geocode(address: str, city: str, zip_code: str):
    """Mirrors pipeline/geocode_provider.py::CensusGeocoder.geocode's request,
    with the one-line string built by the production helper so recording can
    never drift from the string process_queue actually sends."""
    from pipeline.geocode_provider import _full_address
    oneline = _full_address({"address": address, "city": city,
                             "state": "TX", "zip": zip_code})
    data = get_json(
        config.CENSUS_GEOCODER_URL,
        params={"address": oneline, "benchmark": "Public_AR_Current",
                "format": "json"},
        timeout=30,
    )
    if data is None:
        return None, "Census geocoder unreachable"
    return data, None


def fetch_hcad(address: str, zip_code: str):
    """One address's slice of the three hcad_store per-ZIP lookups, in the
    fixture shape the harness replays. Requires the county DuckDB
    (PERMIT_DB_PATH) or the Postgres hcad_* mirror."""
    from pipeline.addr import normalize
    try:
        summaries = hcad_store.query_properties(zip_code)
        extras = hcad_store.query_extra_features(zip_code)
        permits = hcad_store.query_permits(zip_code)
    except Exception as exc:  # no DuckDB file, no hcad_* tables, ...
        return None, f"HCAD store unavailable: {exc}"
    if not summaries and not extras:
        return None, "HCAD store empty for this ZIP"
    key = normalize(address)
    payload = {
        "property_summary": _jsonable(summaries.get(key)),
        "extra_features": extras.get(key),
        "permit_count_24mo": permits.get(key),
    }
    return payload, None


def _jsonable(summary):
    if summary is None:
        return None
    out = dict(summary)
    for field, value in out.items():
        if isinstance(value, (datetime.date, datetime.datetime)):
            out[field] = value.isoformat()[:10]
    return out


def fetch_all(entry: dict) -> tuple[dict, dict]:
    """(payloads, skips) for one corpus entry — payload keys match the
    fixture directories, skipped sources are absent from payloads."""
    address, city, zip_code = entry["address"], entry.get("city", "HOUSTON"), str(entry["zip"])
    payloads, skips = {}, {}
    for kind, result in (
        ("rentcast", fetch_rentcast(address, zip_code)),
        ("acs", fetch_acs(zip_code)),
        ("geocode", fetch_geocode(address, city, zip_code)),
        ("hcad", fetch_hcad(address, zip_code)),
    ):
        payload, skip = result
        if skip:
            skips[kind] = skip
        else:
            payloads[kind] = payload
    return payloads, skips
