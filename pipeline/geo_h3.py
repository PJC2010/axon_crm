"""
H3 hexagon helper (juncto geo layer, Phase 2) — thin wrapper over the optional
`h3` package so the rest of the code never imports it directly and degrades
gracefully when it isn't installed (mirrors how geohash2/uszipcode are treated).

H3 resolution 8 (~0.74 km² hexes) is the heatmap aggregation grid: `properties`
rows carry their cell id in `h3_r8`, and the heatmap endpoint groups by it. When
`h3` is absent, `available()` is False, `to_cell` returns None, and the heatmap
reports itself unavailable rather than erroring.
"""
import logging

from config import GEO_H3_RESOLUTION

log = logging.getLogger(__name__)

try:
    import h3 as _h3
    _AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only where h3 isn't installed
    _h3 = None
    _AVAILABLE = False


def available() -> bool:
    return _AVAILABLE


def to_cell(lat: float | None, lng: float | None, resolution: int = GEO_H3_RESOLUTION) -> str | None:
    """Lat/lng → H3 cell id, or None when h3 is unavailable or inputs are missing."""
    if not _AVAILABLE or lat is None or lng is None:
        return None
    try:
        return _h3.latlng_to_cell(lat, lng, resolution)
    except Exception:  # pragma: no cover - defensive against bad coordinates
        log.debug("h3 latlng_to_cell failed for (%s, %s)", lat, lng)
        return None


def cell_center(cell: str) -> tuple[float, float] | None:
    """H3 cell → (lat, lng) of its center, or None when unavailable."""
    if not _AVAILABLE or not cell:
        return None
    try:
        lat, lng = _h3.cell_to_latlng(cell)
        return lat, lng
    except Exception:  # pragma: no cover
        return None


def cell_boundary(cell: str) -> list[list[float]] | None:
    """H3 cell → GeoJSON-style ring of [lng, lat] vertices, or None when
    unavailable. Lets the heatmap ship polygons for renderers that don't decode
    H3 ids client-side (deck.gl's H3HexagonLayer decodes the id itself)."""
    if not _AVAILABLE or not cell:
        return None
    try:
        return [[lng, lat] for (lat, lng) in _h3.cell_to_boundary(cell)]
    except Exception:  # pragma: no cover
        return None
