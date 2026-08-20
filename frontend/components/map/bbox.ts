/**
 * Viewport-box arithmetic for the pin fetch cache.
 *
 * The map used to refetch up to 2,000 rows on every `moveend`, however small the
 * pan. Fetching a box slightly larger than the viewport and reusing it until the
 * viewport leaves it turns most pans into zero requests, which is both cheaper
 * and visibly smoother — the pins are already there instead of popping in after
 * a debounce plus a round trip.
 *
 * Pure and dependency-free on purpose: an off-by-one in `contains` either
 * refetches constantly (merely wasteful) or never refetches (pins silently stop
 * appearing as you pan), and the second failure is quiet enough to deserve tests.
 */
import type { MapBounds } from '@/lib/types'

export type Bbox = MapBounds

/** How far beyond the viewport to fetch, as a fraction of its own span. */
export const VIEWPORT_PAD = 0.3

/**
 * Grow a box by `pad` of its span on every side.
 *
 * Latitude is clamped to the poles; longitude deliberately is not. The map is
 * hard-bounded to one metro by `lib/serviceArea`, so antimeridian wrapping can't
 * arise here, and pretending to handle it would be untested code that looks
 * reassuring. Revisit if `SERVICE_REGIONS` ever spans the date line.
 */
export function padBbox(b: Bbox, pad: number = VIEWPORT_PAD): Bbox {
  const dLat = (b.max_lat - b.min_lat) * pad
  const dLng = (b.max_lng - b.min_lng) * pad
  return {
    min_lat: Math.max(-90, b.min_lat - dLat),
    max_lat: Math.min(90, b.max_lat + dLat),
    min_lng: b.min_lng - dLng,
    max_lng: b.max_lng + dLng,
  }
}

/**
 * True when `outer` fully encloses `inner`.
 *
 * Inclusive on all four edges: a viewport that exactly matches the fetched box
 * is covered, and treating that as a miss would refetch on every idle at rest.
 */
export function contains(outer: Bbox, inner: Bbox): boolean {
  return (
    outer.min_lat <= inner.min_lat &&
    outer.max_lat >= inner.max_lat &&
    outer.min_lng <= inner.min_lng &&
    outer.max_lng >= inner.max_lng
  )
}
