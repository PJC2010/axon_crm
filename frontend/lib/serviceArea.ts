/**
 * Service-area boundary for the property map.
 *
 * The map cannot be panned or zoomed outside the union of the regions listed in
 * `SERVICE_REGIONS`. Expanding coverage is deliberately a one-entry change:
 * append a region and the union — and therefore the map's reachable area — grows
 * with it. Nothing else in the app needs to change.
 *
 * These are axis-aligned bounding boxes, not true county polygons. A bbox is the
 * right shape here because MapLibre's `maxBounds` only accepts a rectangle; if we
 * ever need to *clip* to a real border (rather than just constrain panning), that
 * belongs in a GeoJSON mask layer, not here.
 */

/** [west, south, east, north], in degrees. */
export type Bbox = [number, number, number, number]

/** MapLibre's `maxBounds` / `fitBounds` shape: [[west, south], [east, north]]. */
export type BoundsTuple = [[number, number], [number, number]]

export interface ServiceRegion {
  /** Stable slug — safe to persist in per-account settings later. */
  id: string
  label: string
  bbox: Bbox
}

/**
 * Regions the product currently serves.
 *
 * To expand: add an entry. e.g.
 *   { id: 'fort-bend-tx', label: 'Fort Bend County, TX', bbox: [-96.03, 29.25, -95.36, 29.85] }
 */
export const SERVICE_REGIONS: ServiceRegion[] = [
  {
    id: 'harris-tx',
    label: 'Harris County, TX',
    // Harris County spans roughly 29.52–30.11 N, -95.96–-94.91 W; padded out to
    // whole-hundredths so the county line never sits flush against the viewport.
    bbox: [-95.97, 29.49, -94.88, 30.18],
  },
]

/**
 * Breathing room (degrees) added around the union so the outermost properties
 * aren't pinned against the edge of the canvas.
 */
export const SERVICE_AREA_PADDING = 0.05

/** Smallest rectangle containing every region. */
export function serviceAreaBbox(regions: ServiceRegion[] = SERVICE_REGIONS): Bbox {
  if (!regions.length) throw new Error('SERVICE_REGIONS must not be empty')
  return regions.reduce<Bbox>(
    ([w, s, e, n], r) => [
      Math.min(w, r.bbox[0]),
      Math.min(s, r.bbox[1]),
      Math.max(e, r.bbox[2]),
      Math.max(n, r.bbox[3]),
    ],
    regions[0].bbox,
  )
}

/** The padded service area, in MapLibre's bounds shape. */
export function serviceAreaBounds(regions: ServiceRegion[] = SERVICE_REGIONS): BoundsTuple {
  const [w, s, e, n] = serviceAreaBbox(regions)
  const p = SERVICE_AREA_PADDING
  return [[w - p, s - p], [e + p, n + p]]
}

/** Human-readable summary for UI copy, e.g. "Harris County, TX". */
export function serviceAreaLabel(regions: ServiceRegion[] = SERVICE_REGIONS): string {
  if (regions.length === 1) return regions[0].label
  return `${regions.length} regions`
}

/** True when a coordinate falls inside the padded service area. */
export function withinServiceArea(lng: number, lat: number): boolean {
  const [[w, s], [e, n]] = serviceAreaBounds()
  return lng >= w && lng <= e && lat >= s && lat <= n
}

/**
 * Intersect a data-derived box with the service area.
 *
 * Used when fitting to a single ZIP: the server already trims outliers with
 * percentiles, but a ZIP holding enough bad rows can still report an extent that
 * spills past the county line. Clamping each edge keeps the resulting fit inside
 * the area the map is allowed to show, so the jump lands somewhere useful instead
 * of zooming out to the boundary. Edges are ordered so a box entirely outside the
 * area collapses onto the nearest edge rather than inverting.
 */
export function clampBoundsToServiceArea(bounds: BoundsTuple): BoundsTuple {
  const [[w, s], [e, n]] = serviceAreaBounds()
  const [[bw, bs], [be, bn]] = bounds
  const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi)
  const west = clamp(bw, w, e)
  const south = clamp(bs, s, n)
  return [
    [west, south],
    [Math.max(clamp(be, w, e), west), Math.max(clamp(bn, s, n), south)],
  ]
}

/**
 * Clamp a data-derived bounds to the service area.
 *
 * The initial map fit is computed from returned cell centroids, and a handful of
 * mis-geocoded rows (a lat/lng that lands in another state) would otherwise drag
 * that fit out to a continental view. Returns null when nothing survives the
 * clamp, so callers can fall back to the full service area.
 */
export function clampToServiceArea(
  lngs: number[],
  lats: number[],
): BoundsTuple | null {
  const [[w, s], [e, n]] = serviceAreaBounds()
  const pts = lngs
    .map((lng, i) => [lng, lats[i]] as const)
    .filter(([lng, lat]) => lng >= w && lng <= e && lat >= s && lat <= n)
  if (!pts.length) return null
  const xs = pts.map(([lng]) => lng)
  const ys = pts.map(([, lat]) => lat)
  return [
    [Math.min(...xs), Math.min(...ys)],
    [Math.max(...xs), Math.max(...ys)],
  ]
}
