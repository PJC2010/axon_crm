/**
 * Continuous color ramps for the choropleth.
 *
 * The cells were shaded by picking one of four grade hues per band. That reads
 * as four unrelated categories, because that is what distinct hues mean: green
 * vs. blue vs. gold vs. red says "different kinds of thing", not "more or less
 * of one thing". But average lead score and signal count are both *ordered* —
 * a cell at 79 and a cell at 81 are nearly the same, and a hue jump at 80
 * claims otherwise.
 *
 * So these are sequential ramps, interpolated by MapLibre rather than bucketed
 * in JS. Reading a gradient is how you see "this block is a bit better than its
 * neighbour", which is the actual question when you're choosing where to knock.
 *
 * The stops live here so the layer paint and the legend gradient are generated
 * from one source. A legend that describes a ramp the layer isn't drawing is the
 * exact failure the grade-color unification existed to kill.
 */
import type { Palette } from './mapPalette'
import type { ColorMode } from './geojson'

/** A ramp stop: the data value and the color at it. */
export interface Stop { at: number; color: string }

/**
 * Score ramp: cold-and-poor through to warm-and-strong.
 *
 * Anchored at the old band boundaries (50 / 65 / 80) so the shading still agrees
 * with how the grades themselves are cut — the change is that it now varies
 * *between* those points instead of stepping at them.
 */
export function scoreRamp(p: Palette): Stop[] {
  return [
    { at: 0,   color: p.gradeD },
    { at: 50,  color: p.gradeC },
    { at: 65,  color: p.gradeB },
    { at: 80,  color: p.gradeA },
    { at: 100, color: p.gradeA },
  ]
}

/**
 * Signals ramp: quiet through to hot.
 *
 * Tops out at 6 rather than running to the data maximum. One block with forty
 * signals would otherwise flatten every other block to the cold end, and the
 * distinction that matters here is "some activity" vs. "a lot", not the exact
 * count — the hover card carries the number.
 */
export function signalsRamp(p: Palette): Stop[] {
  return [
    { at: 0, color: p.none },
    { at: 1, color: p.gradeC },
    { at: 6, color: p.gradeD },
  ]
}

export function rampFor(mode: ColorMode, p: Palette): Stop[] {
  return mode === 'signals' ? signalsRamp(p) : scoreRamp(p)
}

/** The feature property each basis is shaded by. */
export function rampProperty(mode: ColorMode): 'signal_count' | 'avg_score' {
  return mode === 'signals' ? 'signal_count' : 'avg_score'
}

/**
 * Build the MapLibre `interpolate` expression for a ramp.
 *
 * Returned as `unknown` because the style-spec expression types are structural
 * and awkward to satisfy from a builder; the shape is fixed and covered by tests.
 */
export function rampExpression(mode: ColorMode, p: Palette): unknown {
  const stops = rampFor(mode, p)
  return [
    'interpolate', ['linear'],
    // `coalesce` matters: avg_score is null for an unscored cell, and a null in
    // an interpolate input makes MapLibre drop the feature's paint silently.
    ['coalesce', ['get', rampProperty(mode)], 0],
    ...stops.flatMap(s => [s.at, s.color]),
  ]
}

/** CSS gradient for the legend, so it can show the same ramp it's describing. */
export function rampCss(stops: Stop[]): string {
  const min = stops[0].at
  const max = stops[stops.length - 1].at
  const span = max - min || 1
  const parts = stops.map(s => `${s.color} ${Math.round(((s.at - min) / span) * 100)}%`)
  return `linear-gradient(90deg, ${parts.join(', ')})`
}
