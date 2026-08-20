import { describe, it, expect } from 'vitest'
import {
  polygonFromSnapshot, closeRing, ringAreaSqMeters, formatArea, ringContains, ringBounds,
} from './draw'

/**
 * These cover the two failures that would be silent in production: a malformed
 * ring reaching an endpoint that stores `polygon` as an unvalidated dict (the
 * territory gate then quietly stops multiplying, with no error anywhere), and a
 * flat-earth area calculation that reads plausible while being ~15% wrong at
 * Houston's latitude.
 */

// A ~1km square near downtown Houston, closed.
const SQUARE: [number, number][] = [
  [-95.370, 29.760], [-95.360, 29.760], [-95.360, 29.770], [-95.370, 29.770], [-95.370, 29.760],
]

describe('closeRing', () => {
  it('repeats the first point when the ring is open', () => {
    const open: [number, number][] = [[0, 0], [1, 0], [1, 1]]
    expect(closeRing(open)).toEqual([[0, 0], [1, 0], [1, 1], [0, 0]])
  })

  it('leaves an already-closed ring alone', () => {
    expect(closeRing(SQUARE)).toHaveLength(SQUARE.length)
  })

  it('rejects anything that is not a usable ring', () => {
    // Each of these would be accepted verbatim by the server and fail later.
    expect(closeRing([[0, 0], [1, 1]])).toBeNull()          // too few points
    expect(closeRing([[0, 0], [1, 1], [NaN, 2]])).toBeNull() // non-finite
    expect(closeRing([[0, 0], [1, 1], [2]])).toBeNull()      // not a coordinate
    expect(closeRing(null)).toBeNull()
    expect(closeRing('polygon')).toBeNull()
  })
})

describe('polygonFromSnapshot', () => {
  it('returns the newest polygon in the store', () => {
    const p = polygonFromSnapshot([
      { geometry: { type: 'Polygon', coordinates: [SQUARE] } },
      { geometry: { type: 'Polygon', coordinates: [[[0, 0], [2, 0], [2, 2], [0, 0]]] } },
    ])
    expect(p?.coordinates[0][1]).toEqual([2, 0])
  })

  it('ignores the vertex points select mode adds to the store', () => {
    // getSnapshot() returns every feature, not just the drawn shape.
    const p = polygonFromSnapshot([
      { geometry: { type: 'Polygon', coordinates: [SQUARE] } },
      { geometry: { type: 'Point', coordinates: [-95.37, 29.76] } },
    ])
    expect(p?.type).toBe('Polygon')
    expect(p?.coordinates[0]).toHaveLength(SQUARE.length)
  })

  it('is null for an empty or unusable store rather than throwing', () => {
    expect(polygonFromSnapshot([])).toBeNull()
    expect(polygonFromSnapshot(null)).toBeNull()
    expect(polygonFromSnapshot([{ geometry: { type: 'Polygon', coordinates: [] } }])).toBeNull()
    expect(polygonFromSnapshot([{ geometry: { type: 'Polygon', coordinates: [[[0, 0], [1, 1]]] } }])).toBeNull()
  })
})

describe('ringAreaSqMeters', () => {
  it('measures a known square to within a percent', () => {
    // 0.01° of longitude at 29.765°N is 1000 * cos(29.765°) ≈ 965 m; 0.01° of
    // latitude is ~1107 m. So ~1.069 km².
    const area = ringAreaSqMeters(SQUARE)
    expect(area / 1e6).toBeGreaterThan(1.05)
    expect(area / 1e6).toBeLessThan(1.09)
  })

  it('does not use the flat shoelace area', () => {
    // The naive formula gives 0.0001 deg² scaled by a constant and is ~15% high
    // here. If this ever passes, someone has swapped in planar arithmetic.
    const flat = 0.01 * 0.01 * (111_320 ** 2)
    expect(ringAreaSqMeters(SQUARE)).toBeLessThan(flat * 0.95)
  })

  it('is orientation-independent', () => {
    expect(ringAreaSqMeters([...SQUARE].reverse())).toBeCloseTo(ringAreaSqMeters(SQUARE), 0)
  })

  it('is zero for a degenerate ring', () => {
    expect(ringAreaSqMeters([[0, 0], [1, 1]])).toBe(0)
  })
})

describe('formatArea', () => {
  it('uses acres below a square mile and square miles above', () => {
    expect(formatArea(40_468)).toMatch(/acres/)         // 10 acres
    expect(formatArea(5_000_000)).toMatch(/sq mi/)      // ~1.9 sq mi
  })

  it('drops the decimal once the number is large enough not to need it', () => {
    expect(formatArea(50_000_000)).toBe('19 sq mi')
    expect(formatArea(2_023_428)).toBe('500 acres')   // 1 sq mi is 640 acres
  })
})

describe('ringContains', () => {
  it('separates inside from outside', () => {
    expect(ringContains(SQUARE, -95.365, 29.765)).toBe(true)
    expect(ringContains(SQUARE, -95.350, 29.765)).toBe(false)
    expect(ringContains(SQUARE, -95.365, 29.800)).toBe(false)
  })

  it('counts a ray through a vertex once, not twice', () => {
    // The classic ray-casting bug: a horizontal ray hitting a vertex crosses two
    // edges and cancels out, so the point reads as outside. The half-open
    // comparison is what prevents it.
    const diamond: [number, number][] = [[0, 1], [1, 0], [0, -1], [-1, 0], [0, 1]]
    expect(ringContains(diamond, 0, 0)).toBe(true)
  })

  it('handles a concave ring, where a bounding box would not', () => {
    // A U shape: the notch is inside the bbox but outside the polygon.
    const u: [number, number][] = [
      [0, 0], [3, 0], [3, 3], [2, 3], [2, 1], [1, 1], [1, 3], [0, 3], [0, 0],
    ]
    expect(ringContains(u, 0.5, 2)).toBe(true)
    expect(ringContains(u, 1.5, 2)).toBe(false)   // in the notch
  })
})

describe('ringBounds', () => {
  it('returns southwest then northeast, as fitBounds expects', () => {
    expect(ringBounds(SQUARE)).toEqual([[-95.370, 29.760], [-95.360, 29.770]])
  })

  it('is null for an empty ring rather than returning Infinity', () => {
    expect(ringBounds([])).toBeNull()
  })
})
