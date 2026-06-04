"""
Search-area expansion — find ZIPs near a target ZIP so a thin ZIP can be
widened to neighbouring areas.

Uses the optional `uszipcode` library (a bundled SQLite of ZIP centroids +
city/state; no API key, no network). If it isn't installed the functions return
empty lists and the caller simply doesn't expand.
"""
import logging

log = logging.getLogger(__name__)

try:
    from uszipcode import SearchEngine
    _AVAILABLE = True
except Exception:   # pragma: no cover - import guard
    SearchEngine = None
    _AVAILABLE = False


def available() -> bool:
    return _AVAILABLE


def _engine():
    # Simple/default DB is enough for coordinates + city/state.
    return SearchEngine()


def nearby_zips(zip_code: str, radius_miles: float = 5,
                max_zips: int = 10) -> list[str]:
    """ZIPs within `radius_miles` of `zip_code`, nearest first, excluding itself."""
    if not _AVAILABLE:
        return []
    try:
        search = _engine()
        center = search.by_zipcode(zip_code)
        if not center or center.lat is None or center.lng is None:
            return []
        results = search.by_coordinates(
            center.lat, center.lng, radius=radius_miles, returns=max_zips + 1
        )
        out = [z.zipcode for z in results
               if z.zipcode and z.zipcode != zip_code]
        return out[:max_zips]
    except Exception as e:   # pragma: no cover - library/runtime issues
        log.warning("nearby_zips(%s) failed: %s", zip_code, e)
        return []


def city_zips(zip_code: str, max_zips: int = 25) -> list[str]:
    """Other ZIPs in the same city/state as `zip_code`."""
    if not _AVAILABLE:
        return []
    try:
        search = _engine()
        center = search.by_zipcode(zip_code)
        if not center or not center.major_city:
            return []
        results = search.by_city_and_state(
            center.major_city, center.state, returns=max_zips + 1
        )
        out = [z.zipcode for z in results
               if z.zipcode and z.zipcode != zip_code]
        return out[:max_zips]
    except Exception as e:   # pragma: no cover - library/runtime issues
        log.warning("city_zips(%s) failed: %s", zip_code, e)
        return []
