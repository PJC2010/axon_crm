"""
Step 5.5 — Storm / hail event enrichment (FREE, NOAA/IEM).

Fetches Local Storm Reports (hail, thunderstorm wind, tornado) from the Iowa
Environmental Mesonet (IEM) API for the Houston/Galveston NWS Weather Forecast
Office (WFO=HGX). No API key required.

For each property that has been geocoded (lat/lng set by pipeline/geocode.py),
matches storm events within STORM_MATCH_RADIUS_MI and writes:

  last_storm_date   — date of the most recent matched storm
  last_storm_type   — 'hail' | 'wind' | 'tornado'
  hail_size_in      — hail diameter in inches (None for non-hail events)
  storm_count_24mo  — count of distinct storm events within 24 months

These columns immediately improve the `storm` scoring signal for roofing, HVAC,
fencing, and pressure-washing verticals, and accumulate as model features for a
future conversion-probability model.
"""
import logging
import math
from datetime import date, timedelta

from config import STORM_WFO, STORM_LOOKBACK_MONTHS, STORM_MATCH_RADIUS_MI, IEM_LSR_URL
from pipeline.db import get_conn, upsert_properties
from pipeline.http import get_json

log = logging.getLogger(__name__)

# IEM LSR event types we care about, mapped to our normalized labels.
_TYPE_MAP = {
    "HAIL":               "hail",
    "THUNDERSTORM WIND":  "wind",
    "HIGH WIND":          "wind",
    "TORNADO":            "tornado",
    "FUNNEL CLOUD":       "tornado",
}


def _haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in miles between two lat/lon points."""
    r = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return r * 2 * math.asin(math.sqrt(a))


def _fetch_storm_reports(lookback_months: int, wfo: str) -> list[dict]:
    """Return storm report dicts from the IEM Local Storm Report GeoJSON API.

    Each record contains: date (date), storm_type (str), hail_size_in (float|None),
    lat (float), lon (float).
    """
    ets = date.today()
    sts = ets - timedelta(days=int(lookback_months * 30.44))
    url = IEM_LSR_URL
    params = {
        "sts": sts.strftime("%Y%m%dT0000"),
        "ets": ets.strftime("%Y%m%dT2359"),
        "wfo": wfo,
    }
    data = get_json(url, params=params, timeout=30)
    if not data or data.get("type") != "FeatureCollection":
        log.warning("IEM LSR returned no data or unexpected format for WFO=%s", wfo)
        return []

    reports = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        coords = (feature.get("geometry") or {}).get("coordinates")
        if not coords or len(coords) < 2:
            continue
        type_text = (props.get("typetext") or "").upper()
        storm_type = _TYPE_MAP.get(type_text)
        if not storm_type:
            continue
        valid_str = props.get("valid", "")
        try:
            event_date = date.fromisoformat(valid_str[:10])
        except (ValueError, TypeError):
            continue
        magnitude = props.get("magnitude")
        hail_size = None
        if storm_type == "hail":
            try:
                hail_size = float(magnitude)
            except (TypeError, ValueError):
                pass
        reports.append({
            "date": event_date,
            "storm_type": storm_type,
            "hail_size_in": hail_size,
            "lat": float(coords[1]),
            "lon": float(coords[0]),
        })

    log.info("Fetched %d storm reports from IEM (WFO=%s, lookback=%dmo)",
             len(reports), wfo, lookback_months)
    return reports


def _match_property(prop_lat: float, prop_lon: float, reports: list[dict],
                    radius_mi: float, cutoff_date: date) -> dict:
    """Return aggregated storm data for a single property location.

    Considers only reports within `radius_mi` miles and on/after `cutoff_date`.
    Returns empty dict when no matches found.
    """
    nearby = [
        r for r in reports
        if r["date"] >= cutoff_date
        and _haversine_mi(prop_lat, prop_lon, r["lat"], r["lon"]) <= radius_mi
    ]
    if not nearby:
        return {}

    # Most recent event
    latest = max(nearby, key=lambda r: r["date"])
    # Largest hail within the window
    hail_events = [r for r in nearby if r["storm_type"] == "hail" and r["hail_size_in"]]
    max_hail = max((r["hail_size_in"] for r in hail_events), default=None)

    return {
        "last_storm_date": latest["date"],
        "last_storm_type": latest["storm_type"],
        "hail_size_in": max_hail,
        "storm_count_24mo": len(nearby),
    }


def enrich_storm(zip_code: str, account_id: int) -> int:
    """Match NOAA/IEM storm events to properties in one ZIP. Returns update count.

    Only processes properties that have been geocoded (latitude/longitude set).
    Skips properties that already have storm data unless a newer report arrives
    (the upsert only overwrites when the new value is non-None, so partial-fill is safe).
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, address, zip, latitude, longitude "
                "FROM properties "
                "WHERE zip = %s AND account_id = %s "
                "  AND latitude IS NOT NULL AND longitude IS NOT NULL "
                "  AND archived_at IS NULL",
                (zip_code, account_id),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

        if not rows:
            log.info("No geocoded properties in ZIP %s — storm step skipped.", zip_code)
            return 0

        reports = _fetch_storm_reports(STORM_LOOKBACK_MONTHS, STORM_WFO)
        if not reports:
            return 0

        cutoff = date.today() - timedelta(days=int(STORM_LOOKBACK_MONTHS * 30.44))
        updates = []
        for row in rows:
            match = _match_property(row["latitude"], row["longitude"], reports,
                                    STORM_MATCH_RADIUS_MI, cutoff)
            if match:
                match["address"] = row["address"]
                match["zip"] = row["zip"]
                match["enrichment_flags"] = {"storm": "noaa_iem"}
                updates.append(match)

        n = upsert_properties(conn, updates, account_id)
        log.info("Storm enrichment: %d/%d properties matched in ZIP %s",
                 n, len(rows), zip_code)
        return n
    finally:
        conn.close()
