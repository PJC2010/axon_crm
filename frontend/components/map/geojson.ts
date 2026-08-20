/**
 * API payloads → GeoJSON, and the color logic that shades them.
 *
 * Everything here is pure: same inputs, same output, no DOM, no MapLibre, no
 * network. That is deliberate — it is the layer where a renamed property or a
 * shifted band boundary silently blanks part of the map, so it is the layer
 * worth having tests for. `mapPalette.ts` holds the one piece that can't be
 * (it reads `getComputedStyle`).
 */
import ngeohash from 'ngeohash'
import { spriteId } from '@/lib/mapPins'
import type { Palette } from './mapPalette'
import type { MapCell, MapPoint, HeatmapCell } from '@/lib/types'

/** Which metric the choropleth and pins are shaded by. */
export type ColorMode = 'signals' | 'score'

// ── color logic (shared by cells + pins) ─────────────────────────────────────

export function cellColor(c: MapCell, mode: ColorMode, p: Palette): string {
  if (mode === 'signals') {
    // Three bands, not four. The old middle branch read
    // `p.accent === p.gold ? p.danger : p.gold` — a self-comparison of two
    // distinct tokens, which always took the `p.gold` arm, so bands 2 and 3
    // rendered identically.
    if (c.signal_count <= 0) return p.none
    if (c.signal_count <= 3) return p.gradeC
    return p.gradeD
  }
  // score: shade by the cell's average lead score (higher = better prospect)
  const s = c.avg_score
  if (s == null) return p.none
  if (s >= 80) return p.gradeA
  if (s >= 65) return p.gradeB
  if (s >= 50) return p.gradeC
  return p.gradeD
}

export function pointColor(pt: MapPoint, mode: ColorMode, p: Palette): string {
  if (mode === 'signals') return pt.signals.length > 0 ? p.gradeD : p.cool
  switch (pt.score_grade) {
    case 'A': return p.gradeA
    case 'B': return p.gradeB
    case 'C': return p.gradeC
    case 'D': return p.gradeD
    default:  return p.none
  }
}

// ── GeoJSON builders ─────────────────────────────────────────────────────────

/**
 * Geohash-6 cell aggregates → polygons.
 *
 * The API returns only the cell string; the rectangle is decoded here rather
 * than shipped over the wire, which keeps the payload small. `ngeohash` returns
 * `[minLat, minLng, maxLat, maxLng]` — note the lat/lng order is the reverse of
 * GeoJSON's, which is the easy mistake to make when touching this.
 */
export function cellsToGeoJSON(cells: MapCell[], mode: ColorMode, p: Palette) {
  return {
    type: 'FeatureCollection' as const,
    features: cells.map(c => {
      const [minLat, minLng, maxLat, maxLng] = ngeohash.decode_bbox(c.cell)
      return {
        type: 'Feature' as const,
        properties: {
          cell: c.cell,
          name: c.name ?? '',
          leads: c.leads,
          signal_count: c.signal_count,
          avg_score: c.avg_score ?? 0,
          color: cellColor(c, mode, p),
        },
        geometry: {
          type: 'Polygon' as const,
          coordinates: [[
            [minLng, minLat], [maxLng, minLat], [maxLng, maxLat],
            [minLng, maxLat], [minLng, minLat],
          ]],
        },
      }
    }),
  }
}

/**
 * Property pins → GeoJSON.
 *
 * `sprite` is resolved in JS rather than by a MapLibre expression because the
 * sprite id depends on the active color mode, which an expression over feature
 * properties cannot see.
 *
 * `grade`, `status`, `score` and `signals` are carried per feature. The API has
 * always sent them and the renderer used to discard all but one. **`status`,
 * `score` and `signals` are currently groundwork** — nothing reads them yet;
 * they exist for the hover card and the grade-mix cluster aggregation. Don't
 * remove them on the grounds that they look unused, and don't assume from their
 * presence that either feature has landed.
 *
 * `color` is likewise not read by any layer today: the pin layer keys off
 * `sprite`, the highlight uses a flat accent, and the cluster bubbles are a flat
 * fill. It stays because the grade-mix clusters will shade from it.
 */
export function pointsToGeoJSON(points: MapPoint[], mode: ColorMode, p: Palette) {
  return {
    type: 'FeatureCollection' as const,
    features: points.map(pt => {
      const hasSignal = pt.signals.length > 0
      // In signals mode every pin shares one shape and splits on signal state,
      // so the grade ramp shouldn't leak into it.
      const grade = mode === 'signals' ? (hasSignal ? 'S' : 'N') : (pt.score_grade ?? 'N')
      return {
        type: 'Feature' as const,
        properties: {
          id: pt.id,
          address: pt.address ?? '',
          grade,
          status: pt.status,
          score: pt.lead_score ?? null,
          signals: pt.signals.join(', '),
          hasSignal,
          sprite: spriteId(grade, hasSignal),
          color: pointColor(pt, mode, p),
        },
        geometry: { type: 'Point' as const, coordinates: [pt.longitude, pt.latitude] },
      }
    }),
  }
}

/**
 * H3 heatmap hexes → polygons, with a normalized 0–1 `intensity` for shading.
 *
 * `max` is floored at 1 so a set of all-zero cells divides safely rather than
 * producing NaN, which MapLibre would silently refuse to interpolate.
 */
export function heatToGeoJSON(cells: HeatmapCell[]) {
  const max = Math.max(1, ...cells.map(c => c.value ?? 0))
  return {
    type: 'FeatureCollection' as const,
    features: cells
      .filter(c => c.boundary && c.boundary.length >= 3)
      .map(c => ({
        type: 'Feature' as const,
        properties: {
          h3: c.h3,
          value: c.value ?? 0,
          intensity: (c.value ?? 0) / max,
          leads: c.leads,
          customers: c.customers,
        },
        geometry: {
          type: 'Polygon' as const,
          coordinates: [[...c.boundary!, c.boundary![0]]],
        },
      })),
  }
}

/**
 * Cluster hulls / event polygons arrive already shaped as FeatureCollections.
 *
 * Both endpoints can return null geometry — a customer cluster with fewer than
 * three points has no hull — and MapLibre throws on a null-geometry feature, so
 * they're dropped here rather than at the call site.
 */
function dropNullGeometry(fc: { features: Array<{ geometry: unknown }> } | null) {
  const features = (fc?.features ?? []).filter(f => f.geometry != null)
  return { type: 'FeatureCollection' as const, features: features as GeoJSON.Feature[] }
}

export const clustersToGeoJSON = dropNullGeometry
export const eventsToGeoJSON = dropNullGeometry
