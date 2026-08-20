import { describe, it, expect } from 'vitest'
import {
  pointColor, cellsToGeoJSON, pointsToGeoJSON,
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
    const [f] = cellsToGeoJSON([cell()]).features
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
    // and silently drops the feature's paint, so an unscored cell would render
    // as a hole rather than as the bottom of the ramp.
    const [f] = cellsToGeoJSON([cell({ name: null, avg_score: null })]).features
    expect(f.properties.name).toBe('')
    expect(f.properties.avg_score).toBe(0)
  })

  it('carries both ramp inputs and the grade mix', () => {
    // Both bases must ride along or switching basis would need a refetch; the
    // grade counts back the hover card.
    const [f] = cellsToGeoJSON([cell({ signal_count: 3, avg_score: 71, grade_a: 5, grade_d: 1 })]).features
    expect(f.properties.signal_count).toBe(3)
    expect(f.properties.avg_score).toBe(71)
    expect(f.properties.grade_a).toBe(5)
    expect(f.properties.grade_d).toBe(1)
  })

  it('returns an empty collection for no cells', () => {
    expect(cellsToGeoJSON([]).features).toEqual([])
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
