import { describe, it, expect } from 'vitest'
import {
  GRADE_TOKENS, GRADE_ACTION, STATUS_TOKENS,
  gradeTokens, gradeVarName, statusTokens,
} from './gradeColors'

/**
 * These tests exist because this mapping was duplicated in four components that
 * disagreed with each other, and nothing caught it. The specific assertions
 * below are the specific bugs that shipped — each one would have failed.
 */

describe('grade colors', () => {
  it('paints grade B as the data blue, never the interactive accent', () => {
    // The bug: PropertyMap used --color-accent (the app's turquoise affordance
    // color) for grade B, so B-grade pins read as selected controls. A data
    // category must never share a hue with an interaction state.
    expect(GRADE_TOKENS.B.fg).toBe('var(--color-info)')
    expect(GRADE_TOKENS.B.fg).not.toContain('accent')
  })

  it('paints grade C as gold, not the warning intent', () => {
    // TerritoryFilter used --color-warning here while everything else used gold.
    expect(GRADE_TOKENS.C.fg).toBe('var(--color-gold)')
  })

  it('gives every grade a distinct foreground except F, which mirrors D', () => {
    const distinct = new Set([GRADE_TOKENS.A, GRADE_TOKENS.B, GRADE_TOKENS.C, GRADE_TOKENS.D].map(t => t.fg))
    expect(distinct.size).toBe(4)
    expect(GRADE_TOKENS.F).toEqual(GRADE_TOKENS.D)
  })

  it('resolves grades case-insensitively and falls back for unknown input', () => {
    expect(gradeTokens('a')).toEqual(GRADE_TOKENS.A)
    expect(gradeTokens('Z')).toEqual(GRADE_TOKENS.F)
  })

  it('returns null rather than a fallback color for absent grades', () => {
    // An ungraded lead must render as "—", not as a low grade. Conflating
    // "not scored yet" with "scored badly" is a real product error.
    expect(gradeTokens(null)).toBeNull()
    expect(gradeTokens(undefined)).toBeNull()
    expect(gradeTokens('')).toBeNull()
  })

  it('exposes the raw CSS variable name for WebGL consumers', () => {
    // MapLibre compiles paint properties into shaders and cannot read CSS
    // variables, so the map resolves these names itself via getComputedStyle.
    expect(gradeVarName('A')).toBe('--color-success')
    expect(gradeVarName('B')).toBe('--color-info')
    expect(gradeVarName(null)).toBeNull()
    expect(gradeVarName('Z')).toBeNull()
  })

  it('keeps the var() tokens and the raw var names in agreement', () => {
    for (const g of ['A', 'B', 'C', 'D', 'F'] as const) {
      expect(GRADE_TOKENS[g].fg).toBe(`var(${gradeVarName(g)})`)
    }
  })

  it('frames every grade as an action, not just a letter', () => {
    for (const g of ['A', 'B', 'C', 'D', 'F'] as const) {
      expect(GRADE_ACTION[g].startsWith(`${g} — `)).toBe(true)
    }
  })
})

describe('status colors', () => {
  it('keeps lost and not_interested distinct', () => {
    // The bug: StatusSelect had these two swapped relative to StatusPill, so the
    // same lead read as danger on one screen and neutral on another. A lost deal
    // is a negative outcome worth seeing; "not interested" is a terminal state,
    // not a failure, so it recedes.
    expect(STATUS_TOKENS.lost.fg).toBe('var(--color-danger)')
    expect(STATUS_TOKENS.not_interested.fg).toBe('var(--color-ink-400)')
    expect(STATUS_TOKENS.lost).not.toEqual(STATUS_TOKENS.not_interested)
  })

  it('covers every LeadStatus the API can return', () => {
    // Mirrors the STATUSES list the map's filter dropdown offers. A status
    // missing here silently renders as "New", which is worse than an error.
    const statuses = ['new', 'contacted', 'qualified', 'quote_sent', 'won', 'lost', 'not_interested', 'converted']
    for (const s of statuses) {
      expect(STATUS_TOKENS[s], `missing status: ${s}`).toBeDefined()
      expect(statusTokens(s)).toBe(STATUS_TOKENS[s])
    }
  })

  it('falls back to the new-lead style for an unknown status', () => {
    expect(statusTokens('nonsense')).toEqual(STATUS_TOKENS.new)
  })

  it('gives won and converted the same treatment', () => {
    // Both are customers as far as the pipeline is concerned.
    expect(STATUS_TOKENS.won.fg).toBe(STATUS_TOKENS.converted.fg)
  })
})
