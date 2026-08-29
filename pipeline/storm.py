"""
Step 5.5 — Storm / hail / freeze event enrichment (FREE, NOAA/IEM).

Fetches Local Storm Reports (hail, thunderstorm wind, tornado, tropical cyclone,
winter events) from the Iowa Environmental Mesonet (IEM) API. The NWS Weather
Forecast Office is resolved per ZIP from its centroid via the NWS point API, so
any market works without configuration; STORM_WFO is only a fallback. Neither
API requires a key.

For each property that has been geocoded (lat/lng set by pipeline/geocode.py),
matches events within STORM_MATCH_RADIUS_MI and writes:

  last_storm_date   — date of the most recent matched damage storm
  last_storm_type   — 'hail' | 'wind' | 'tornado'
  hail_size_in      — largest hail diameter in inches (None if no hail matched)
  storm_count_24mo  — count of distinct damage-storm events within 24 months
  last_freeze_date  — date of the most recent matched freeze event
  freeze_count_24mo — count of distinct freeze events within the window

**Damage storms and freezes are tracked in separate columns and must stay that
way.** They sell different trades — hail/wind sells roofing, fencing and
pressure-washing; a freeze sells HVAC and, through multi-day outages, solar with
storage — and they arrive in the same market in the same year. Merging them into
one last_* pair means whichever landed later erases the other: Houston logged 120
SNOW reports in January 2025 against 122 HAIL reports over the same 24 months, so
one shared column would have blanked the storm signal for every roofing lead in
the market.

These columns feed the `storm`, `hail` and `freeze` scoring signals and
accumulate as model features for the conversion-probability model.
"""
import logging
import math
from datetime import date, timedelta

from config import (
    STORM_WFO, STORM_LOOKBACK_MONTHS, STORM_MATCH_RADIUS_MI, IEM_LSR_URL,
    NWS_POINTS_URL, NWS_USER_AGENT, STORM_FETCH_CHUNK_MONTHS,
)
from pipeline.db import get_conn, upsert_properties
from pipeline.http import get_json

log = logging.getLogger(__name__)

# IEM LSR `typetext` values we care about, mapped to our normalized labels.
# These strings must match the feed exactly — they are the raw NWS product
# abbreviations, not the spelled-out event names. Every string in both maps below
# was read off a live LSR response; do not add one from memory.
#
# Deliberately excluded: MARINE TSTM WIND and WATERSPOUT (over open water, so
# they describe no property damage even when a coastal parcel falls inside the
# match radius), and the precipitation/flood types.
#
# The flood exclusion is load-bearing rather than incidental, and a hurricane is
# where it shows. Beryl's July 2024 track through Harris County produced
# TROPICAL CYCLONE, NON-TSTM WND GST, STORM SURGE, FLASH FLOOD and COASTAL FLOOD
# reports in one window. Only the wind half drives roofing work: wind damage is a
# homeowners-policy claim, while hurricane flood damage runs through NFIP and
# buys no roof. Keying storm exposure to a general hurricane path rather than to
# wind and hail would score the flooded side of the storm as demand.
_TYPE_MAP = {
    "HAIL":              "hail",
    "TSTM WND DMG":      "wind",
    "TSTM WND GST":      "wind",
    "NON-TSTM WND DMG":  "wind",
    "NON-TSTM WND GST":  "wind",
    "HIGH SUST WINDS":   "wind",
    "TROPICAL CYCLONE":  "wind",
    "TORNADO":           "tornado",
    "FUNNEL CLOUD":      "tornado",
    "LANDSPOUT":         "tornado",
}

# Winter events, kept in their own map and written to their own columns (see the
# module docstring). Plain SNOW is included on purpose: in the markets that
# weight the freeze signal it marks a hard freeze well outside local design
# temperatures — Houston's whole January 2025 event reports as SNOW, SLEET,
# FREEZING RAIN and ICE STORM together. That reasoning does not travel. A market
# in the freeze belt, where snow is a weekly fact rather than an equipment event,
# must revisit this list before weighting `freeze` at all, or the signal will
# saturate for every lead and rank nobody.
_FREEZE_TYPE_MAP = {
    "SNOW":          "freeze",
    "HEAVY SNOW":    "freeze",
    "SLEET":         "freeze",
    "FREEZING RAIN": "freeze",
    "ICE STORM":     "freeze",
    "SNOW/ICE DMG":  "freeze",
    "EXTREME COLD":  "freeze",
    "WIND CHILL":    "freeze",
}

# One lookup over both families; the partition happens at match time.
_ALL_TYPE_MAP = {**_TYPE_MAP, **_FREEZE_TYPE_MAP}

assert not (set(_TYPE_MAP) & set(_FREEZE_TYPE_MAP)), \
    "a typetext in both maps would be counted as damage and as freeze"

# IEM caps a single LSR response at this many features and gives no truncation
# flag, so an over-broad query silently loses data. Scoping to one WFO keeps a
# 24-month pull around 800 reports; we warn if we ever approach the ceiling.
_IEM_RESULT_CAP = 10000

# lat/lng (rounded) → WFO code. WFO boundaries never move mid-run, so this is
# safe to hold for the life of the process.
_wfo_cache: dict[tuple[float, float], str] = {}

# (wfo, lookback_months, fetch_date) → parsed reports. A pipeline run walks many
# ZIPs that share one forecast office; without this each would refetch the whole
# window. Keyed by date so a long-lived scheduler picks up new reports daily.
_report_cache: dict[tuple[str, int, date], list[dict]] = {}


def _haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in miles between two lat/lon points."""
    r = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return r * 2 * math.asin(math.sqrt(a))


def _resolve_wfo(lat: float, lon: float) -> str | None:
    """Return the NWS Weather Forecast Office code covering a lat/lng, or None.

    Uses the free, keyless NWS point-metadata API. Results are cached per
    rounded coordinate. Returns None on any failure so the caller can fall back
    to the configured default rather than fetching the wrong region's reports.
    """
    key = (round(lat, 2), round(lon, 2))
    if key in _wfo_cache:
        return _wfo_cache[key]

    data = get_json(
        f"{NWS_POINTS_URL}/{key[0]},{key[1]}",
        headers={"User-Agent": NWS_USER_AGENT, "Accept": "application/geo+json"},
        timeout=15,
    )
    wfo = ((data or {}).get("properties") or {}).get("cwa")
    if not wfo:
        log.warning("NWS point lookup gave no WFO for %s,%s", key[0], key[1])
        return None

    _wfo_cache[key] = wfo
    return wfo


def _fetch_lsr_window(sts: date, ets: date, wfo: str) -> list[dict]:
    """Return raw GeoJSON features for one WFO over one date window."""
    # Timestamps are %Y%m%d%H%M — the API 422s on any other layout, and the
    # param is `wfos` (plural); a `wfo` key is ignored and silently returns
    # every office nationwide.
    params = {
        "sts": sts.strftime("%Y%m%d%H%M"),
        "ets": ets.strftime("%Y%m%d%H%M"),
        "wfos": wfo,
    }
    data = get_json(IEM_LSR_URL, params=params, timeout=30)
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        log.warning("IEM LSR returned no data or unexpected format for WFO=%s (%s→%s)",
                    wfo, sts, ets)
        return []

    features = data.get("features", [])
    if len(features) >= _IEM_RESULT_CAP:
        log.warning(
            "IEM LSR hit the %d-feature cap for WFO=%s (%s→%s); reports were "
            "silently dropped. Lower STORM_FETCH_CHUNK_MONTHS.",
            _IEM_RESULT_CAP, wfo, sts, ets,
        )
    return features


def _fetch_storm_reports(lookback_months: int, wfo: str) -> list[dict]:
    """Return storm report dicts from the IEM Local Storm Report GeoJSON API.

    Each record contains: date (date), storm_type (str), hail_size_in (float|None),
    lat (float), lon (float).

    The window is fetched in STORM_FETCH_CHUNK_MONTHS slices because IEM caps a
    response at _IEM_RESULT_CAP features with no truncation flag — a 24-month
    pull for an active office exceeds that on snow reports alone. Results are
    memoized per (WFO, lookback, day) so ZIPs sharing an office fetch once.
    """
    today = date.today()
    cache_key = (wfo, lookback_months, today)
    if cache_key in _report_cache:
        return _report_cache[cache_key]
    # Reports change daily; drop entries from previous days rather than grow.
    for stale in [k for k in _report_cache if k[2] != today]:
        del _report_cache[stale]

    window_start = today - timedelta(days=int(lookback_months * 30.44))
    chunk = timedelta(days=int(max(1, STORM_FETCH_CHUNK_MONTHS) * 30.44))

    features: list[dict] = []
    cursor = window_start
    while cursor < today:
        chunk_end = min(cursor + chunk, today)
        features.extend(_fetch_lsr_window(cursor, chunk_end, wfo))
        cursor = chunk_end

    reports = []
    for feature in features:
        props = feature.get("properties", {})
        coords = (feature.get("geometry") or {}).get("coordinates")
        if not coords or len(coords) < 2:
            continue
        type_text = (props.get("typetext") or "").upper()
        storm_type = _ALL_TYPE_MAP.get(type_text)
        if not storm_type:
            continue
        valid_str = props.get("valid", "")
        try:
            event_date = date.fromisoformat(valid_str[:10])
        except (ValueError, TypeError):
            continue
        hail_size = None
        if storm_type == "hail":
            # `magf` is already a float; `magnitude` is the same value as a
            # string and is "" on reports that carry no measurement.
            magnitude = props.get("magf")
            if magnitude is None:
                magnitude = props.get("magnitude")
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

    log.info("Fetched %d storm reports from IEM (WFO=%s, lookback=%dmo, %d raw)",
             len(reports), wfo, lookback_months, len(features))
    _report_cache[cache_key] = reports
    return reports


# Normalized labels that describe physical damage, as opposed to a freeze.
_DAMAGE_TYPES = frozenset(_TYPE_MAP.values())


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

    # Partition before aggregating. storm_count_24mo and last_storm_* must stay
    # damage-only: a market that gets both hail and freezes would otherwise see
    # its storm count inflated by every snow report and its last_storm_date
    # replaced by whichever family happened to arrive last.
    damage = [r for r in nearby if r["storm_type"] in _DAMAGE_TYPES]
    freezes = [r for r in nearby if r["storm_type"] == "freeze"]

    out: dict = {}
    if damage:
        latest = max(damage, key=lambda r: r["date"])
        # Largest hail within the window — severity, not just occurrence. An
        # adjuster approves a full replacement on granule loss, which is a
        # function of stone size.
        hail_events = [r for r in damage if r["storm_type"] == "hail" and r["hail_size_in"]]
        out["last_storm_date"] = latest["date"]
        out["last_storm_type"] = latest["storm_type"]
        out["hail_size_in"] = max((r["hail_size_in"] for r in hail_events), default=None)
        out["storm_count_24mo"] = len(damage)
    if freezes:
        out["last_freeze_date"] = max(r["date"] for r in freezes)
        out["freeze_count_24mo"] = len(freezes)
    return out


def enrich_storm(zip_code: str, account_id: int) -> int:
    """Match NOAA/IEM storm events to properties in one ZIP. Returns update count.

    Only processes properties that have been geocoded (latitude/longitude set).
    Skips properties that already have storm data unless a newer report arrives
    (the upsert only overwrites when the new value is non-None, so partial-fill is safe).

    The NWS forecast office is resolved from the ZIP's own centroid, so this
    works for any market rather than only the configured default.
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

        # Resolve the forecast office from this ZIP's centroid. A ZIP can
        # straddle a WFO boundary; the centroid picks the office covering the
        # bulk of it, and the radius match discards anything too far out.
        centroid_lat = sum(r["latitude"] for r in rows) / len(rows)
        centroid_lon = sum(r["longitude"] for r in rows) / len(rows)
        wfo = _resolve_wfo(centroid_lat, centroid_lon) or STORM_WFO

        reports = _fetch_storm_reports(STORM_LOOKBACK_MONTHS, wfo)
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
