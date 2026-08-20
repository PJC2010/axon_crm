'use client'
import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { GRADE_TOKENS, GRADE_ACTION } from '@/lib/gradeColors'
import { rampCss } from '../ramp'
import type { ColorMode } from '../geojson'

/**
 * Key for whichever metric the map is currently shaded by.
 *
 * Swatches read from `lib/gradeColors`, the same source the layers paint from,
 * so the legend cannot describe a color the map isn't drawing. That mattered:
 * this component previously hardcoded grade B as `--color-accent` and so did the
 * pin layer — they were wrong *together*, which is exactly why the drift went
 * unnoticed for so long.
 */
export function Legend({ mode, collapsible }: { mode: ColorMode; collapsible?: boolean }) {
  // Collapsed by default on mobile so it doesn't cover the map (the parent
  // remounts this via `key` when crossing the breakpoint).
  const [open, setOpen] = useState(!collapsible)

  // Cells are shaded by a continuous ramp, pins by discrete grade. So the legend
  // has two halves: a gradient strip describing the choropleth, and the grade
  // swatches describing the pins. Showing only swatches implied the cells were
  // bucketed, which is exactly the misreading the ramp exists to fix.
  //
  // The strip is built from the same stops the layer paints from — via CSS
  // variables rather than the resolved palette, because the palette needs a live
  // document and this renders during SSR too.
  const rampCssValue = mode === 'signals'
    ? rampCss([
        { at: 0, color: 'var(--color-ink-200)' },
        { at: 1, color: GRADE_TOKENS.C.fg },
        { at: 6, color: GRADE_TOKENS.D.fg },
      ])
    : rampCss([
        { at: 0,   color: GRADE_TOKENS.D.fg },
        { at: 50,  color: GRADE_TOKENS.C.fg },
        { at: 65,  color: GRADE_TOKENS.B.fg },
        { at: 80,  color: GRADE_TOKENS.A.fg },
        { at: 100, color: GRADE_TOKENS.A.fg },
      ])

  const ends = mode === 'signals' ? ['Quiet', 'Hot'] : ['Weak', 'Strong']

  const items = mode === 'signals'
    ? []
    : (['A', 'B', 'C', 'D'] as const).map(g => ({
        c: GRADE_TOKENS[g].fg,
        t: GRADE_ACTION[g],
      }))

  return (
    <div style={{
      // Explicit, and deliberately below ClusterActionPanel (3): when both are
      // up on a narrow screen the action panel is the thing being acted on.
      // Previously neither declared one and stacking fell to DOM order.
      position: 'absolute', bottom: 16, left: 16, zIndex: 2, background: 'var(--color-paper)',
      border: '1px solid var(--color-ink-200)', borderRadius: 'var(--radius-card)',
      boxShadow: 'var(--shadow-card)', padding: '10px 12px', fontSize: 11, color: 'var(--color-ink-700)',
    }}>
      {collapsible ? (
        <button
          onClick={() => setOpen(v => !v)}
          aria-expanded={open}
          style={{
            display: 'flex', alignItems: 'center', gap: 6, padding: 0, margin: open ? '0 0 6px' : 0,
            border: 'none', background: 'transparent', cursor: 'pointer',
            fontSize: 11, fontWeight: 600, color: 'var(--color-ink-900)',
          }}
        >
          {mode === 'signals' ? 'Intent signals' : 'Lead score'}
          {open ? <ChevronDown size={12} strokeWidth={1.5} /> : <ChevronUp size={12} strokeWidth={1.5} />}
        </button>
      ) : (
        <div style={{ fontWeight: 600, marginBottom: 6, color: 'var(--color-ink-900)' }}>
          {mode === 'signals' ? 'Intent signals' : 'Lead score'}
        </div>
      )}
      {open && (
        <>
          {/* Blocks: the continuous ramp the choropleth actually paints. */}
          <div style={{ marginBottom: items.length ? 8 : 0 }}>
            <div style={{
              height: 8, width: 132, borderRadius: 2,
              background: rampCssValue, border: '1px solid var(--color-ink-200)',
            }} />
            <div style={{
              display: 'flex', justifyContent: 'space-between',
              fontSize: 10, color: 'var(--color-ink-500)', marginTop: 2,
            }}>
              <span>{ends[0]}</span><span>{ends[1]}</span>
            </div>
          </div>
          {/* Pins: discrete, because a lead's grade is a category. */}
          {items.map(i => (
            <div key={i.t} style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 3 }}>
              <span style={{ width: 12, height: 12, borderRadius: 3, background: i.c, flexShrink: 0 }} />
              {i.t}
            </div>
          ))}
        </>
      )}
    </div>
  )
}
