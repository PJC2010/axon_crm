import { describe, it, expect } from 'vitest'
import { gradeClusterProperties, CLUSTER_GRADES } from './clusterDonuts'

/**
 * `gradeClusterProperties` is handed straight to MapLibre as a source option and
 * consumed by Supercluster. A key that doesn't match what the donut reader looks
 * for produces clusters with no tallies — which renders as a plain grey ring
 * with a count, i.e. exactly the flat bubble this feature replaced, and with no
 * error to say so.
 */
describe('gradeClusterProperties', () => {
  it('emits one accumulator per grade, keyed to match the reader', () => {
    const props = gradeClusterProperties()
    expect(Object.keys(props).sort()).toEqual(CLUSTER_GRADES.map(g => `g${g}`).sort())
  })

  it('builds a sum-of-matches expression for each grade', () => {
    const props = gradeClusterProperties() as Record<string, unknown[]>
    // Supercluster's shape: ['+', <per-feature value>] where the value is 1 when
    // the feature matches and 0 otherwise.
    expect(props.gA).toEqual(['+', ['case', ['==', ['get', 'grade'], 'A'], 1, 0]])
    expect(props.gN).toEqual(['+', ['case', ['==', ['get', 'grade'], 'N'], 1, 0]])
  })

  it('covers both the score grades and the signals-mode pseudo-grades', () => {
    // A cluster in signals mode holds S/N features; without these the donut
    // would have nothing to draw on that basis.
    for (const g of ['A', 'B', 'C', 'D', 'S', 'N']) {
      expect(CLUSTER_GRADES).toContain(g)
    }
  })

  it('references the same feature property pointsToGeoJSON writes', () => {
    // The contract that actually breaks in practice: the aggregation reads
    // `grade`, so pointsToGeoJSON must emit `grade`.
    const props = gradeClusterProperties() as Record<string, unknown[]>
    for (const key of Object.keys(props)) {
      expect(JSON.stringify(props[key])).toContain('"grade"')
    }
  })
})
