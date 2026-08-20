/**
 * The single source of truth for lead-grade and lead-status colors.
 *
 * These mappings used to live in four places that disagreed with each other:
 * `ds/ScoreBadge` (canonical), `TerritoryFilter` (grade C as `warning` instead
 * of `gold`), `PropertyMap` (grade B as `accent` instead of `info`), and
 * `StatusSelect` (`lost` and `not_interested` swapped relative to
 * `StatusPill`). Same lead, different color depending on which surface you were
 * looking at.
 *
 * Grade B is the one worth calling out. The map painted it `--color-accent` —
 * the app's *interactive/primary* turquoise — which made B-grade pins read as
 * selected controls rather than as data. Data categories and affordances must
 * not share a hue; `--color-info` is the data blue.
 *
 * Two shapes are exported because the map needs both:
 *   • `GRADE_TOKENS` / `STATUS_TOKENS` — CSS `var(...)` strings for DOM styling.
 *   • `gradeVarName()` — the raw custom-property *name*, because WebGL can't
 *     read CSS variables and the map has to resolve them to hex at runtime via
 *     `getComputedStyle` (see PropertyMap's `readPalette`).
 */

export type Grade = 'A' | 'B' | 'C' | 'D' | 'F'

/** Foreground / background token pair per grade. `bg` is the soft chip tint. */
export const GRADE_TOKENS: Record<Grade, { fg: string; bg: string }> = {
  A: { fg: 'var(--color-success)', bg: 'var(--color-success-bg)' },
  B: { fg: 'var(--color-info)',    bg: 'var(--color-info-bg)' },
  C: { fg: 'var(--color-gold)',    bg: 'var(--color-gold-soft)' },
  D: { fg: 'var(--color-danger)',  bg: 'var(--color-danger-bg)' },
  F: { fg: 'var(--color-danger)',  bg: 'var(--color-danger-bg)' },
}

/**
 * The bare custom-property name behind each grade's foreground, for callers
 * that must resolve to a concrete color (WebGL paint properties, canvas).
 */
const GRADE_VARS: Record<Grade, string> = {
  A: '--color-success',
  B: '--color-info',
  C: '--color-gold',
  D: '--color-danger',
  F: '--color-danger',
}

export function gradeVarName(grade: string | null | undefined): string | null {
  if (!grade) return null
  return GRADE_VARS[grade.toUpperCase() as Grade] ?? null
}

export function gradeTokens(grade: string | null | undefined) {
  if (!grade) return null
  return GRADE_TOKENS[grade.toUpperCase() as Grade] ?? GRADE_TOKENS.F
}

/**
 * Grades framed as actions rather than letters — the tooltip/screen-reader text
 * tells the user what to *do*. Kept here so every surface says the same thing.
 */
export const GRADE_ACTION: Record<Grade, string> = {
  A: 'A — call first',
  B: 'B — worth a timely follow-up',
  C: 'C — when you have capacity',
  D: 'D — low priority',
  F: 'F — low priority',
}

/**
 * Pipeline status colors + labels.
 *
 * `lost` is danger and `not_interested` is neutral ink — deliberately, and this
 * is the pairing `StatusPill` already shipped. A lost deal is a negative
 * outcome worth seeing; "not interested" is a terminal state, not a failure, so
 * it recedes. `StatusSelect` had these two swapped.
 */
export const STATUS_TOKENS: Record<string, { fg: string; bg: string; label: string }> = {
  new:            { fg: 'var(--color-ink-500)',    bg: 'var(--color-ink-50)',     label: 'New' },
  contacted:      { fg: 'var(--color-info)',       bg: 'var(--color-info-bg)',    label: 'Contacted' },
  qualified:      { fg: 'var(--color-accent-300)', bg: 'var(--color-accent-100)', label: 'Qualified' },
  quote_sent:     { fg: 'var(--color-gold)',       bg: 'var(--color-gold-soft)',  label: 'Quote Sent' },
  won:            { fg: 'var(--color-success)',    bg: 'var(--color-success-bg)', label: 'Won' },
  lost:           { fg: 'var(--color-danger)',     bg: 'var(--color-danger-bg)',  label: 'Lost' },
  not_interested: { fg: 'var(--color-ink-400)',    bg: 'var(--color-ink-50)',     label: 'Not Interested' },
  converted:      { fg: 'var(--color-success)',    bg: 'var(--color-success-bg)', label: 'Converted' },
}

export function statusTokens(status: string) {
  return STATUS_TOKENS[status] ?? STATUS_TOKENS.new
}
