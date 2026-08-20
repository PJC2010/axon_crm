/**
 * Pure helpers for the map's draw tools.
 *
 * Everything here is dependency-free so it can be unit-tested without a map, a
 * canvas or Terra Draw itself. The session lifecycle — which genuinely needs all
 * three — lives in `useDrawTools.ts`.
 *
 * ## Why the polygon is validated client-side
 *
 * `PUT /geo/service-area` and `POST /geo/events` both take `polygon` as an
 * unvalidated `dict`: no GeoJSON schema check, no ring-closure check. A
 * malformed value is stored verbatim and fails *silently* later, when
 * `_ring_from_geojson` returns `None` and the territory gate quietly stops
 * multiplying anything. Terra Draw emits well-formed closed rings, so this is
 * belt-and-braces rather than a fix — but it is the only place that can catch a
 * bad ring before it becomes a scoring bug with no error attached to it.
 */

import type { Palette } from './mapPalette'

/** A ring needs three distinct corners plus the repeated closing point. */
export const POLYGON_MIN_POINTS = 4

/** The GeoJSON the geo endpoints accept. */
export interface DrawnPolygon {
  type: 'Polygon'
  coordinates: [number, number][][]
}

/** One feature as Terra Draw's `getSnapshot()` returns it. */
export interface SnapshotFeature {
  id?: string | number
  geometry?: { type?: string; coordinates?: unknown }
  properties?: Record<string, unknown>
}

/**
 * Pull a submittable polygon out of a Terra Draw snapshot.
 *
 * `getSnapshot()` returns an *array of Features*, not a FeatureCollection, and
 * it contains every feature in the store — including the vertex points that
 * select mode adds. So this filters by geometry rather than trusting position,
 * and closes the ring if the mode somehow didn't.
 */
export function polygonFromSnapshot(features: SnapshotFeature[] | null | undefined): DrawnPolygon | null {
  if (!features?.length) return null
  for (let i = features.length - 1; i >= 0; i--) {   // newest first
    const g = features[i]?.geometry
    if (g?.type !== 'Polygon') continue
    const rings = g.coordinates as unknown
    if (!Array.isArray(rings) || !rings.length) continue
    const ring = closeRing(rings[0] as [number, number][])
    if (!ring || ring.length < POLYGON_MIN_POINTS) continue
    return { type: 'Polygon', coordinates: [ring] }
  }
  return null
}

/**
 * Repeat the first point at the end if it isn't already there.
 *
 * Returns null for anything that isn't a usable ring, so a caller can't
 * accidentally submit `[[NaN, NaN]]` — the server would take it.
 */
export function closeRing(ring: unknown): [number, number][] | null {
  if (!Array.isArray(ring) || ring.length < 3) return null
  const out: [number, number][] = []
  for (const p of ring) {
    if (!Array.isArray(p) || p.length < 2) return null
    const [lng, lat] = p as [number, number]
    if (!Number.isFinite(lng) || !Number.isFinite(lat)) return null
    out.push([lng, lat])
  }
  const first = out[0], last = out[out.length - 1]
  if (first[0] !== last[0] || first[1] !== last[1]) out.push([first[0], first[1]])
  return out
}

// ── size ─────────────────────────────────────────────────────────────────────

const EARTH_RADIUS_M = 6_378_137
const SQ_M_PER_SQ_MI = 2_589_988.11
const SQ_M_PER_ACRE = 4_046.8564224

/**
 * Spherical area of a ring, in square metres.
 *
 * The shoelace formula on raw lng/lat is wrong by roughly `1/cos(latitude)` —
 * about 15% at Houston's latitude — which is the difference between a territory
 * that looks right and a quote that's priced off a bad number. This is the
 * standard spherical-excess formula (the one PostGIS and Turf both use), which
 * costs three trig calls per vertex and is exact enough at any territory size.
 */
export function ringAreaSqMeters(ring: [number, number][]): number {
  if (ring.length < 3) return 0
  const rad = (d: number) => (d * Math.PI) / 180
  let total = 0
  for (let i = 0; i < ring.length; i++) {
    const [lng1, lat1] = ring[i]
    const [lng2, lat2] = ring[(i + 1) % ring.length]
    total += rad(lng2 - lng1) * (2 + Math.sin(rad(lat1)) + Math.sin(rad(lat2)))
  }
  return Math.abs((total * EARTH_RADIUS_M * EARTH_RADIUS_M) / 2)
}

/**
 * Human-readable size for the confirm panel.
 *
 * Acres below a square mile because that's how land is talked about at the
 * neighbourhood scale a hail swath or a single subdivision occupies; square
 * miles above it, because "9,000 acres" means nothing to anyone.
 */
export function formatArea(sqMeters: number): string {
  const sqMi = sqMeters / SQ_M_PER_SQ_MI
  if (sqMi >= 1) return `${sqMi.toFixed(sqMi >= 10 ? 0 : 1)} sq mi`
  const acres = sqMeters / SQ_M_PER_ACRE
  return `${acres < 10 ? acres.toFixed(1) : Math.round(acres).toLocaleString()} acres`
}

// ── point-in-polygon ─────────────────────────────────────────────────────────

/**
 * Ray-casting hit test for one ring.
 *
 * Hand-rolled rather than `@turf/boolean-point-in-polygon`: that package's own
 * bundle is 1.8 KB, but it pulls `point-in-polygon-hao` →
 * `robust-predicates` (~48.6 KB min) for exact arithmetic on degenerate cases
 * — collinear points, a vertex landing exactly on an edge. This tests
 * hand-drawn polygons against property pins; a pin exactly on a boundary can
 * fall either way without anyone noticing, so the robustness isn't worth 50 KB
 * on a phone.
 *
 * The `(yi > y) !== (yj > y)` form is the standard half-open convention: it
 * counts each edge's lower endpoint and not its upper one, so a ray passing
 * exactly through a vertex crosses once rather than zero or two times.
 */
export function ringContains(ring: [number, number][], lng: number, lat: number): boolean {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]
    const [xj, yj] = ring[j]
    if ((yi > lat) !== (yj > lat) && lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) {
      inside = !inside
    }
  }
  return inside
}

/** Bounding box of a ring, as MapLibre's `fitBounds` wants it. */
export function ringBounds(ring: [number, number][]): [[number, number], [number, number]] | null {
  if (!ring.length) return null
  let minLng = Infinity, minLat = Infinity, maxLng = -Infinity, maxLat = -Infinity
  for (const [lng, lat] of ring) {
    if (lng < minLng) minLng = lng
    if (lng > maxLng) maxLng = lng
    if (lat < minLat) minLat = lat
    if (lat > maxLat) maxLat = lat
  }
  return [[minLng, minLat], [maxLng, maxLat]]
}

// ── styling ──────────────────────────────────────────────────────────────────

/**
 * Terra Draw mode styles, from the same palette the rest of the map paints from.
 *
 * Terra Draw takes flat hex strings, not CSS variables — it writes these into
 * feature properties that MapLibre paint expressions read, so a `var(--x)` would
 * arrive at the GPU as an unparseable color and the feature would silently not
 * render. `readPalette()` has already resolved them against the live document.
 */
export function polygonStyles(pal: Palette) {
  return {
    fillColor: pal.accent as `#${string}`,
    fillOpacity: 0.18,
    outlineColor: pal.accent as `#${string}`,
    outlineWidth: 2,
    closingPointColor: pal.gradeA as `#${string}`,
    closingPointWidth: 5,
    closingPointOutlineColor: pal.body as `#${string}`,
    closingPointOutlineWidth: 2,
  }
}

export function pointStyles(pal: Palette) {
  return {
    pointColor: pal.accent as `#${string}`,
    pointWidth: 7,
    pointOutlineColor: pal.body as `#${string}`,
    pointOutlineWidth: 2,
  }
}

// ── blast radius ─────────────────────────────────────────────────────────────

/**
 * A closed ring approximating a circle of `radiusM` around a point.
 *
 * Drawn as a real polygon rather than a `circle` layer because MapLibre's
 * `circle-radius` is in *screen pixels*: a 150 m ring would grow and shrink
 * relative to the streets as the map zooms, which is exactly backwards for a
 * "how far can I walk" overlay.
 *
 * Longitude is scaled by `1/cos(lat)` so the shape is a circle on the ground
 * rather than an ellipse — at Houston's latitude the unscaled version is ~13%
 * too narrow, which would understate the walkable area in the direction reps
 * actually walk.
 */
export function circleRing(
  center: [number, number], radiusM: number, steps = 64,
): [number, number][] {
  const [lng, lat] = center
  const rad = (d: number) => (d * Math.PI) / 180
  const dLat = (radiusM / EARTH_RADIUS_M) * (180 / Math.PI)
  const dLng = dLat / Math.max(Math.cos(rad(lat)), 1e-6)
  const ring: [number, number][] = []
  for (let i = 0; i < steps; i++) {
    const t = (i / steps) * 2 * Math.PI
    ring.push([lng + dLng * Math.cos(t), lat + dLat * Math.sin(t)])
  }
  ring.push([ring[0][0], ring[0][1]])
  return ring
}

/** Metres as a rep would say them: feet up close, miles once it's a drive. */
export function formatDistance(meters: number): string {
  const feet = meters * 3.28084
  if (feet < 1000) return `${Math.round(feet / 10) * 10} ft`
  const miles = meters / 1609.344
  return `${miles.toFixed(miles < 10 ? 1 : 0)} mi`
}
