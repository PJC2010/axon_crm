'use client'
import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { GRADE_TOKENS, GRADE_ACTION } from '@/lib/gradeColors'
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

  const items = mode === 'signals'
    ? [
        { c: GRADE_TOKENS.D.fg, t: 'Hot — recent signals' },
        { c: GRADE_TOKENS.C.fg, t: 'Some signal activity' },
        // Matches `readPalette().none` — both resolve `--color-ink-200`. Named
        // here rather than pulled from the palette because the palette needs a
        // live document and this component renders during SSR.
        { c: 'var(--color-ink-200)', t: 'No recent signals' },
      ]
    : (['A', 'B', 'C', 'D'] as const).map(g => ({
        c: GRADE_TOKENS[g].fg,
        t: GRADE_ACTION[g],
      }))

  return (
    <div style={{
      position: 'absolute', bottom: 16, left: 16, background: 'var(--color-paper)',
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
      {open && items.map(i => (
        <div key={i.t} style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 3 }}>
          <span style={{ width: 12, height: 12, borderRadius: 3, background: i.c, flexShrink: 0 }} />
          {i.t}
        </div>
      ))}
    </div>
  )
}
