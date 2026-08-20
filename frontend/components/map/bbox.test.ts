import { describe, it, expect } from 'vitest'
import { padBbox, contains, VIEWPORT_PAD, type Bbox } from './bbox'

/**
 * The failure modes here are asymmetric, which is why they're tested.
 *
 * `contains` returning false too often just refetches — wasteful but visible and
 * self-correcting. Returning true too often means the map stops fetching as you
 * pan and pins silently stop appearing, with nothing in the console. The second
 * is the one worth a net.
 */

const box = (min_lng: number, min_lat: number, max_lng: number, max_lat: number): Bbox =>
  ({ min_lng, min_lat, max_lng, max_lat })

// A Houston-ish viewport.
const view = box(-95.40, 29.74, -95.34, 29.78)

describe('padBbox', () => {
  it('grows the box by the pad fraction of its own span on each side', () => {
    const p = padBbox(view, 0.5)
    // span: 0.06 lng, 0.04 lat -> pad 0.03 lng, 0.02 lat per side
    expect(p.min_lng).toBeCloseTo(-95.43, 10)
    expect(p.max_lng).toBeCloseTo(-95.31, 10)
    expect(p.min_lat).toBeCloseTo(29.72, 10)
    expect(p.max_lat).toBeCloseTo(29.80, 10)
  })

  it('always produces a box that contains the original', () => {
    for (const pad of [0, 0.1, VIEWPORT_PAD, 1, 3]) {
      expect(contains(padBbox(view, pad), view), `pad=${pad}`).toBe(true)
    }
  })

  it('clamps latitude to the poles', () => {
    const polar = padBbox(box(-10, 80, 10, 89), 2)
    expect(polar.max_lat).toBe(90)
    expect(polar.min_lat).toBeGreaterThanOrEqual(-90)
  })

  it('handles a degenerate zero-span box without inverting it', () => {
    const p = padBbox(box(-95.37, 29.76, -95.37, 29.76))
    expect(p.min_lng).toBeLessThanOrEqual(p.max_lng)
    expect(p.min_lat).toBeLessThanOrEqual(p.max_lat)
  })
})

describe('contains', () => {
  it('accepts a viewport strictly inside the fetched box', () => {
    expect(contains(padBbox(view), box(-95.39, 29.75, -95.35, 29.77))).toBe(true)
  })

  it('accepts an exactly equal box', () => {
    // Treating equality as a miss would refetch on every idle while at rest.
    expect(contains(view, view)).toBe(true)
  })

  it('rejects a viewport that has escaped in any single direction', () => {
    const outer = padBbox(view)   // ±0.018 lng, ±0.012 lat around `view`
    const escapes: Array<[string, Bbox]> = [
      ['west',  box(-96.0, 29.75, -95.35, 29.77)],
      ['east',  box(-95.39, 29.75, -94.0, 29.77)],
      ['south', box(-95.39, 29.0, -95.35, 29.77)],
      ['north', box(-95.39, 29.75, -95.35, 30.5)],
    ]
    for (const [dir, v] of escapes) {
      expect(contains(outer, v), `should refetch when panned ${dir}`).toBe(false)
    }
  })

  it('rejects a zoomed-out viewport larger than what was fetched', () => {
    // Zooming out is the case a naive centre-point check would miss entirely.
    expect(contains(padBbox(view), box(-96, 29, -94, 30))).toBe(false)
  })

  it('is not symmetric', () => {
    const outer = padBbox(view)
    expect(contains(outer, view)).toBe(true)
    expect(contains(view, outer)).toBe(false)
  })
})
