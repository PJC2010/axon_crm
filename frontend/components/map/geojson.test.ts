import { describe, it, expect } from 'vitest'
import {
  cellColor, pointColor, cellsToGeoJSON, pointsToGeoJSON,
  heatToGeoJSON, clustersToGeoJSON,
} from './geojson'
import type { Palette } from './mapPalette'
import type { MapCell, MapPoint, HeatmapCell } from '@/lib/types'

/**
 * A stand-in palette with identifiable values, so a test failure says *which*
 * color was picked rather than just that two hexes differ.
 */
const P = {
  none: 'NONE', cool: 'COOL', line: 'LINE', accent: 'ACCENT',
  gradeA: 'A', gradeB: 'B', gradeC: 'C', gradeD: 'D',
  heatLow: 'HL', heatMid: 'HM', heatHigh: 'HH',
  customer: 'CUST', alert: 'ALERT',
  body: 'BODY', ink: 'INK', neutral: 'NEUTRAL',
} as Palette

function cell(over: Partial<MapCell> = {}): MapCell {
  return {
    cell: '9vk1s2', name: null, leads: 1, avg_score: null,
    grade_a: 0, grade_b: 0, grade_c: 0, grade_d: 0,
    signal_count: 0, lat: 29.76, lng: -95.37, ...over,
  }
}

function point(over: Partial<MapPoint> = {}): MapPoint {
  return {
    id: 1, address: '1 Ash St', latitude: 29.76, longitude: -95.37,
    lead_score: 50, score_grade: 'C', status: 'new', signals: [], ...over,
  }
}

describe('cellColor — signals basis', () => {
  it('renders three distinct bands, not four', () => {
    // The bug: the middle branch read `p.accent === p.gold ? p.danger : p.gold`,
    // a self-comparison of two distinct tokens that always took the same arm, so
    // bands 2 and 3 painted identically. Four thresholds, three colors.
    const colors = [0, 1, 3, 4, 50].map(n => cellColor(cell({ signal_count: n }), 'signals', P))
    expect(colors).toEqual([P.none, P.gradeC, P.gradeC, P.gradeD, P.gradeD])
    expect(new Set(colors).size).toBe(3)
  })

  it('treats a zero or negative count as "no signals"', () => {
    expect(cellColor(cell({ signal_count: 0 }), 'signals', P)).toBe(P.none)
    expect(cellColor(cell({ signal_count: -1 }), 'signals', P)).toBe(P.none)
  })

  it('ignores avg_score entirely on the signals basis', () => {
    const hot = cell({ signal_count: 9, avg_score: 5 })
    expect(cellColor(hot, 'signals', P)).toBe(P.gradeD)
  })
})

describe('cellColor — score basis', () => {
  it('maps each band boundary to the grade above it', () => {
    // Boundaries are inclusive lower bounds; 80/65/50 are the cut points.
    const at = (s: number) => cellColor(cell({ avg_score: s }), 'score', P)
    expect(at(100)).toBe(P.gradeA)
    expect(at(80)).toBe(P.gradeA)
    expect(at(79.9)).toBe(P.gradeB)
    expect(at(65)).toBe(P.gradeB)
    expect(at(64.9)).toBe(P.gradeC)
    expect(at(50)).toBe(P.gradeC)
    expect(at(49.9)).toBe(P.gradeD)
    expect(at(0)).toBe(P.gradeD)
  })

  it('distinguishes an unscored cell from a badly scored one', () => {
    // null must not collapse to grade D — "we haven't scored this block" and
    // "this block is poor" are different claims.
    expect(cellColor(cell({ avg_score: null }), 'score', P)).toBe(P.none)
    expect(cellColor(cell({ avg_score: 0 }), 'score', P)).toBe(P.gradeD)
  })
})

describe('pointColor', () => {
  it('splits on signal presence, not grade, on the signals basis', () => {
    expect(pointColor(point({ signals: ['permit'], score_grade: 'A' }), 'signals', P)).toBe(P.gradeD)
    expect(pointColor(point({ signals: [], score_grade: 'A' }), 'signals', P)).toBe(P.cool)
  })

  it('maps each grade on the score basis, and unknown grades to neutral', () => {
    expect(pointColor(point({ score_grade: 'A' }), 'score', P)).toBe(P.gradeA)
    expect(pointColor(point({ score_grade: 'B' }), 'score', P)).toBe(P.gradeB)
    expect(pointColor(point({ score_grade: 'C' }), 'score', P)).toBe(P.gradeC)
    expect(pointColor(point({ score_grade: 'D' }), 'score', P)).toBe(P.gradeD)
    expect(pointColor(point({ score_grade: null }), 'score', P)).toBe(P.none)
  })
})

describe('cellsToGeoJSON', () => {
  it('emits a closed ring in GeoJSON lng/lat order', () => {
    // ngeohash returns [minLat, minLng, maxLat, maxLng] — the reverse of
    // GeoJSON's axis order. Getting this backwards puts Houston in Somalia.
    const [f] = cellsToGeoJSON([cell()], 'signals', P).features
    const ring = f.geometry.coordinates[0]
    expect(ring).toHaveLength(5)
    expect(ring[0]).toEqual(ring[4])            // closed
    for (const [lng, lat] of ring) {
      expect(lng).toBeLessThan(0)               // western hemisphere
      expect(lat).toBeGreaterThan(0)            // northern hemisphere
      expect(Math.abs(lng)).toBeGreaterThan(Math.abs(lat))  // Houston: ~-95 vs ~29
    }
  })

  it('substitutes safe defaults for the nullable fields layers read', () => {
    // `avg_score: 0` rather than null matters: MapLibre cannot interpolate null
    // and silently drops the feature's paint.
    const [f] = cellsToGeoJSON([cell({ name: null, avg_score: null })], 'signals', P).features
    expect(f.properties.name).toBe('')
    expect(f.properties.avg_score).toBe(0)
  })

  it('returns an empty collection for no cells', () => {
    expect(cellsToGeoJSON([], 'signals', P).features).toEqual([])
  })
})

describe('pointsToGeoJSON', () => {
  it('emits every property the layers and cluster aggregation read', () => {
    // A renamed key here blanks a layer with no error, so the contract is pinned
    // explicitly rather than inferred.
    const [f] = pointsToGeoJSON([point()], 'score', P).features
    for (const k of ['id', 'address', 'grade', 'status', 'score', 'signals', 'hasSignal', 'sprite', 'color']) {
      expect(f.properties, `missing feature property: ${k}`).toHaveProperty(k)
    }
  })

  it('uses the signal pseudo-grades in signals mode and real grades in score mode', () => {
    const withSig = point({ signals: ['permit'], score_grade: 'A' })
    expect(pointsToGeoJSON([withSig], 'signals', P).features[0].properties.grade).toBe('S')
    expect(pointsToGeoJSON([point({ signals: [] })], 'signals', P).features[0].properties.grade).toBe('N')
    expect(pointsToGeoJSON([withSig], 'score', P).features[0].properties.grade).toBe('A')
  })

  it('picks a sprite that matches the grade it emitted', () => {
    // grade and sprite are derived together; if they ever disagree the pin draws
    // the wrong color from the one the tooltip would report.
    for (const mode of ['signals', 'score'] as const) {
      const [f] = pointsToGeoJSON([point({ signals: ['permit'], score_grade: 'B' })], mode, P).features
      expect(f.properties.sprite).toBe(`pin-${f.properties.grade}-sig`)
    }
  })

  it('falls back to the neutral grade for an unscored lead', () => {
    const [f] = pointsToGeoJSON([point({ score_grade: null })], 'score', P).features
    expect(f.properties.grade).toBe('N')
    expect(f.properties.sprite).toBe('pin-N')
  })

  it('flattens signals to a string and coerces a null address', () => {
    // MapLibre feature properties can't hold arrays, and an address-less contact
    // (inbound call/SMS lead) is a real row in this table.
    const [f] = pointsToGeoJSON([point({ signals: ['permit', 'permit2'], address: null })], 'score', P).features
    expect(f.properties.signals).toBe('permit, permit2')
    expect(f.properties.address).toBe('')
  })

  it('emits coordinates as [lng, lat]', () => {
    const [f] = pointsToGeoJSON([point({ latitude: 29.76, longitude: -95.37 })], 'score', P).features
    expect(f.geometry.coordinates).toEqual([-95.37, 29.76])
  })
})

describe('heatToGeoJSON', () => {
  const hex = (over: Partial<HeatmapCell> = {}): HeatmapCell => ({
    h3: '88a', value: 1, leads: 1, customers: 1, avg_score: 50,
    boundary: [[-95.4, 29.7], [-95.3, 29.7], [-95.3, 29.8]], center: [29.75, -95.35], ...over,
  })

  it('normalizes intensity against the maximum value', () => {
    const fc = heatToGeoJSON([hex({ value: 5 }), hex({ value: 10 })])
    expect(fc.features.map(f => f.properties.intensity)).toEqual([0.5, 1])
  })

  it('never divides by zero when every cell is empty', () => {
    // max is floored at 1; NaN would make MapLibre refuse to interpolate, and it
    // does so silently.
    const fc = heatToGeoJSON([hex({ value: 0 }), hex({ value: null })])
    for (const f of fc.features) expect(f.properties.intensity).toBe(0)
  })

  it('drops cells without a usable boundary ring', () => {
    const fc = heatToGeoJSON([
      hex(),
      hex({ boundary: null }),
      hex({ boundary: [[-95.4, 29.7], [-95.3, 29.7]] }),  // only 2 points
    ])
    expect(fc.features).toHaveLength(1)
  })

  it('closes the boundary ring', () => {
    const [f] = heatToGeoJSON([hex()]).features
    const ring = f.geometry.coordinates[0]
    expect(ring[0]).toEqual(ring[ring.length - 1])
  })

  it('handles an empty input without producing NaN', () => {
    expect(heatToGeoJSON([]).features).toEqual([])
  })
})

describe('clustersToGeoJSON', () => {
  it('drops null-geometry features', () => {
    // A DBSCAN cluster with fewer than 3 points has no hull, and MapLibre throws
    // on a null-geometry feature.
    const fc = clustersToGeoJSON({
      features: [{ geometry: { type: 'Polygon', coordinates: [] } }, { geometry: null }],
    })
    expect(fc.features).toHaveLength(1)
  })

  it('tolerates a null collection', () => {
    expect(clustersToGeoJSON(null).features).toEqual([])
  })
})
