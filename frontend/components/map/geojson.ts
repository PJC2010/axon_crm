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
import type { MapCell, MapPoint, HeatmapCell, NeighborHit } from '@/lib/types'
import { circleRing } from './draw'

/** Which metric the choropleth and pins are shaded by. */
export type ColorMode = 'signals' | 'score'

// ── color logic ──────────────────────────────────────────────────────────────
//
// Cells are no longer colored here. They used to be bucketed into one of four
// grade hues in JS and baked onto each feature; they're now shaded by a
// continuous MapLibre ramp (see ./ramp.ts), because average score and signal
// count are ordered values and four distinct hues claim they're four unrelated
// categories. Pins stay in JS — their sprite depends on the mode, which an
// expression over feature properties can't see.

export function pointColor(pt: MapPoint, mode: ColorMode, p: Palette): string {
  if (mode === 'signals') return pt.signals.length > 0 ? p.gradeD : p.cool
  return gradeDotColor(pt.score_grade, p)
}

/** Grade → dot color. Shared so a pin and a blast-radius hit can't disagree. */
export function gradeDotColor(grade: string | null | undefined, p: Palette): string {
  switch (grade) {
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
export function cellsToGeoJSON(cells: MapCell[]) {
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
          // The ramp reads these directly, so both bases must ride along —
          // which is what makes switching basis a paint update, not a refetch.
          signal_count: c.signal_count,
          // `coalesce` has to stay — a null reaching `interpolate` makes
          // MapLibre drop the feature's paint entirely, leaving a hole. But 0 is
          // the ramp's bottom stop, the red reserved for the worst blocks, so a
          // cell whose leads have simply never been scored would be painted as
          // the worst block on the map. `scored` keeps "no score" distinct from
          // "scored zero"; the ramp branches on it.
          avg_score: c.avg_score ?? 0,
          scored: c.avg_score != null,
          // Grade mix, for the cell hover card. Fetched all along and discarded
          // until now.
          grade_a: c.grade_a, grade_b: c.grade_b,
          grade_c: c.grade_c, grade_d: c.grade_d,
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

/**
 * Blast radius around a completed job: the walkable ring plus its ranked hits.
 *
 * One FeatureCollection rather than two sources, because the ring and the pins
 * are one answer to one question and are always shown and cleared together.
 * The layers separate them with a `geometry-type` filter.
 *
 * `rank` rides along so the panel's list and the map agree on the order — the
 * endpoint sorts by distance then blended score, and re-sorting on either side
 * would quietly break that pairing.
 */
export function blastToGeoJSON(
  center: [number, number], radiusM: number, hits: NeighborHit[], p: Palette,
): GeoJSON.FeatureCollection {
  const ring: GeoJSON.Feature = {
    type: 'Feature',
    geometry: { type: 'Polygon', coordinates: [circleRing(center, radiusM)] },
    properties: { kind: 'ring' },
  }
  const pins: GeoJSON.Feature[] = hits.map((h, i) => ({
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [h.longitude, h.latitude] },
    properties: {
      kind: 'hit',
      id: h.id,
      rank: i + 1,
      color: gradeDotColor(h.score_grade, p),
    },
  }))
  return { type: 'FeatureCollection', features: [ring, ...pins] }
}
