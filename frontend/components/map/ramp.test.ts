import { describe, it, expect } from 'vitest'
import { scoreRamp, signalsRamp, rampFor, rampProperty, rampExpression, rampCss } from './ramp'
import type { Palette } from './mapPalette'

const P = {
  none: 'NONE', cool: 'COOL', line: 'LINE', accent: 'ACCENT',
  gradeA: 'A', gradeB: 'B', gradeC: 'C', gradeD: 'D',
  heatLow: 'HL', heatMid: 'HM', heatHigh: 'HH',
  customer: 'CUST', alert: 'ALERT',
  body: 'BODY', ink: 'INK', neutral: 'NEUTRAL',
} as Palette

/**
 * The ramp replaced four hard-bucketed grade hues. These tests pin the two
 * things that would break it silently: stops out of ascending order (MapLibre
 * rejects the whole expression, so the layer renders untinted) and a missing
 * null guard on the input (a null makes MapLibre drop the feature's paint).
 */
describe('ramp stops', () => {
  it('keeps stops in strictly ascending order', () => {
    // MapLibre requires ascending inputs and throws on the whole expression
    // otherwise — which loses the entire choropleth, not just one cell.
    for (const stops of [scoreRamp(P), signalsRamp(P)]) {
      for (let i = 1; i < stops.length; i++) {
        expect(stops[i].at).toBeGreaterThanOrEqual(stops[i - 1].at)
      }
    }
  })

  it('anchors the score ramp at the grade band boundaries', () => {
    // The shading still agrees with how grades are cut; what changed is that it
    // varies between those points instead of stepping at them.
    const ats = scoreRamp(P).map(s => s.at)
    expect(ats).toContain(50)
    expect(ats).toContain(65)
    expect(ats).toContain(80)
  })

  it('runs the score ramp from the weakest grade to the strongest', () => {
    const stops = scoreRamp(P)
    expect(stops[0].color).toBe(P.gradeD)
    expect(stops[stops.length - 1].color).toBe(P.gradeA)
  })

  it('starts the signals ramp at the neutral "nothing here" color', () => {
    // Zero signals must not read as a weak signal — it's an absence.
    expect(signalsRamp(P)[0]).toEqual({ at: 0, color: P.none })
  })

  it('caps the signals ramp rather than running to the data maximum', () => {
    // One block with forty signals would otherwise flatten everything else to
    // the cold end.
    const top = signalsRamp(P).at(-1)!
    expect(top.at).toBeLessThanOrEqual(10)
  })

  it('selects the ramp and the property together', () => {
    expect(rampFor('score', P)).toEqual(scoreRamp(P))
    expect(rampFor('signals', P)).toEqual(signalsRamp(P))
    expect(rampProperty('score')).toBe('avg_score')
    expect(rampProperty('signals')).toBe('signal_count')
  })
})

describe('rampExpression', () => {
  /** Score mode wraps its interpolate in a `case`; signals mode doesn't. */
  const interpolateOf = (e: unknown[]) => (e[0] === 'case' ? e[2] as unknown[] : e)

  it('builds a linear interpolate over the right property', () => {
    const e = interpolateOf(rampExpression('score', P) as unknown[])
    expect(e[0]).toBe('interpolate')
    expect(e[1]).toEqual(['linear'])
    expect(e[2]).toEqual(['coalesce', ['get', 'avg_score'], 0])
  })

  it('paints a never-scored cell neutral, not worst-grade red', () => {
    // The coalesce that keeps MapLibre from dropping the paint lands a null on
    // the ramp's bottom stop — which in score mode is the grade-D red for the
    // worst blocks. A block nobody has scored is an absence, not a bad score.
    const e = rampExpression('score', P) as unknown[]
    expect(e[0]).toBe('case')
    expect(e[1]).toEqual(['get', 'scored'])
    expect(e[3]).toBe(P.none)
    expect(e[3]).not.toBe(P.gradeD)
  })

  it('leaves the signals ramp unwrapped, because zero signals really is zero', () => {
    expect((rampExpression('signals', P) as unknown[])[0]).toBe('interpolate')
  })

  it('guards against a null input', () => {
    // avg_score is null for an unscored cell. Feeding null to interpolate makes
    // MapLibre silently drop the feature's paint, so the cell renders as a hole.
    for (const mode of ['score', 'signals'] as const) {
      expect(JSON.stringify(rampExpression(mode, P))).toContain('coalesce')
    }
  })

  it('flattens to alternating value/color pairs', () => {
    const e = rampExpression('signals', P) as unknown[]
    const pairs = e.slice(3)
    expect(pairs).toHaveLength(signalsRamp(P).length * 2)
    for (let i = 0; i < pairs.length; i += 2) {
      expect(typeof pairs[i]).toBe('number')
      expect(typeof pairs[i + 1]).toBe('string')
    }
  })
})

describe('rampCss', () => {
  it('renders a left-to-right gradient covering 0–100%', () => {
    const css = rampCss(scoreRamp(P))
    expect(css.startsWith('linear-gradient(90deg,')).toBe(true)
    expect(css).toContain('0%')
    expect(css).toContain('100%')
  })

  it('places interior stops proportionally to their value', () => {
    // The legend has to describe the ramp the layer draws; even spacing would
    // misreport where the color actually changes.
    const css = rampCss([{ at: 0, color: 'X' }, { at: 25, color: 'Y' }, { at: 100, color: 'Z' }])
    expect(css).toContain('Y 25%')
  })

  it('survives a single-stop ramp without dividing by zero', () => {
    expect(rampCss([{ at: 5, color: 'X' }])).toContain('X 0%')
  })
})
