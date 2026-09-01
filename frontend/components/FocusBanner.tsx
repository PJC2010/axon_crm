'use client'
import { Sparkles } from 'lucide-react'
import type { FocusInfo } from '@/lib/types'

/**
 * Banner for the automatic focus view (pipeline/focus.py): the server narrows
 * the default lead list to the account's top grade bands, and this strip says
 * so — "Showing your top 214 leads (B-grade and up) · Show all 41,334" — with
 * one click to lift or restore it. Renders nothing when the account has no
 * focus cutoff (thin book, or nothing scored yet). Styled after
 * ScoringQuotaBanner (ModuleGate.tsx).
 */
export function FocusBanner({ focus, onToggle }: {
  focus: FocusInfo | null
  onToggle: (showAll: boolean) => void
}) {
  if (!focus) return null

  const gradeLabel = focus.grade ? ` (${focus.grade}-grade and up)` : ''
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
      padding: '8px 16px', fontSize: 12.5,
      background: 'var(--color-surface)',
      borderBottom: '1px solid var(--color-ink-200)',
      color: 'var(--color-ink-700)',
    }}>
      <Sparkles size={13} strokeWidth={1.5} style={{ color: 'var(--color-accent)', flexShrink: 0 }} />
      {focus.active ? (
        <span>
          Showing your top <b>{focus.shown_total.toLocaleString()}</b> leads{gradeLabel}
        </span>
      ) : (
        <span>
          Showing all <b>{focus.all_total.toLocaleString()}</b> leads
        </span>
      )}
      <button
        type="button"
        onClick={() => onToggle(focus.active)}
        style={{
          background: 'none', border: 'none', padding: 0, font: 'inherit',
          fontWeight: 600, color: 'var(--color-accent-300)', cursor: 'pointer',
        }}
      >
        {focus.active
          ? `Show all ${focus.all_total.toLocaleString()}`
          : `Show top ${focus.shown_total.toLocaleString()}`}
      </button>
    </div>
  )
}
