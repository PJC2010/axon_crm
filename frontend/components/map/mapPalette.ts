/**
 * Design-system colors, resolved to concrete hex for WebGL.
 *
 * MapLibre paint properties are compiled into shaders, so they cannot read CSS
 * custom properties — every color has to be a literal by the time it reaches a
 * layer. This module is the one place that crosses that boundary: it reads the
 * live computed values off `:root` and hands back plain strings.
 *
 * Grade colors come from `lib/gradeColors` rather than being named here, so the
 * map cannot drift from `ScoreBadge` again. It previously painted grade B in
 * `--color-accent` — the app's interactive turquoise — which made B-grade pins
 * read as selected controls rather than as data.
 *
 * Kept separate from `geojson.ts` because it is the only part of the map's pure
 * layer that touches the DOM (`getComputedStyle`), which makes it the one part
 * that can't be unit-tested without a browser.
 */
import { gradeVarName, type Grade } from '@/lib/gradeColors'
import type { PinPalette } from '@/lib/mapPins'

/**
 * Read the palette off the document root.
 *
 * Fallbacks are the dark-system token values, not the Tailwind-ish hexes that
 * used to sit here: if `getComputedStyle` ever comes back empty (very early
 * paint) the map should degrade to Axon's palette, not to a light theme that no
 * longer exists anywhere in the app.
 */
export function readPalette() {
  const cs = getComputedStyle(document.documentElement)
  const v = (name: string, fallback: string) => cs.getPropertyValue(name).trim() || fallback
  const grade = (g: Grade, fallback: string) => v(gradeVarName(g) as string, fallback)
  return {
    none:   v('--color-ink-200', '#404854'),
    cool:   v('--color-ocean',   '#3fa6da'),
    line:   v('--color-ink-300', '#5f6b7c'),
    accent: v('--color-accent',  '#00a396'),   // UI affordance only — never a data category
    // Grade ramp, keyed to the shared source of truth.
    gradeA: grade('A', '#32a467'),
    gradeB: grade('B', '#3fa6da'),
    gradeC: grade('C', '#f0b726'),
    gradeD: grade('D', '#e76a6e'),
    // Overlay semantics, deliberately named for what they *mean* rather than
    // for their hue, so an overlay can be recolored without anyone wondering
    // whether it also moves a lead grade. They currently share hues with the
    // grade ramp; that is a coincidence of the palette, not a coupling.
    heatLow:  v('--color-ocean',   '#3fa6da'),  // heatmap: coolest
    heatMid:  v('--color-gold',    '#f0b726'),
    heatHigh: v('--color-rose',    '#f5498b'),  // heatmap: hottest
    customer: v('--color-moss',    '#32a467'),  // customer-cluster hulls
    alert:    v('--color-danger',  '#e76a6e'),  // active event polygons
    // Pin artwork: slate body, light letter, muted border for "no grade".
    body:     v('--color-surface',  '#2f343c'),
    ink:      v('--color-ink-900',  '#f6f7f9'),
    neutral:  v('--color-ink-300',  '#5f6b7c'),
  }
}

export type Palette = ReturnType<typeof readPalette>

/** The subset of the palette the pin sprites need, in their own shape. */
export function pinPalette(p: Palette): PinPalette {
  return {
    gradeA: p.gradeA, gradeB: p.gradeB, gradeC: p.gradeC, gradeD: p.gradeD,
    body: p.body, ink: p.ink, neutral: p.neutral,
    signal: p.gradeC,  // gold badge — "there's recent intent here"
  }
}
