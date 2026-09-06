'use client'
import { AlertTriangle } from 'lucide-react'

/* Rendering for figures the server could not measure in time.

   Every admin panel that reads under api/deps.py::soft_query returns a
   `degraded` list naming the blocks it had to give up on; those numbers arrive
   as null. The rule (CLAUDE.md) is that a null renders as "—", never as 0 — a
   dash says "unknown", a zero says "none", and an operator acts differently on
   the two. */

/** "—" for an unmeasured figure, else the locale-formatted number. */
export function dash(v: number | null | undefined, opts?: Intl.NumberFormatOptions): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return v.toLocaleString(undefined, opts)
}

/** "—" or "12.3%" (the server rounds; this only formats). */
export function pctText(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${v.toFixed(1)}%`
}

export interface DegradedSource {
  source: string
  items: string[]
}

/** One line per source that could not fully answer. Renders nothing when
 *  every source is whole, so it can sit unconditionally at the top of a page. */
export function DegradedBanner({ sources }: { sources: DegradedSource[] }) {
  const shown = sources.filter((s) => s.items.length > 0)
  if (shown.length === 0) return null
  return (
    <div
      role="status"
      style={{
        display: 'flex', gap: 10, alignItems: 'flex-start',
        background: 'var(--color-gold-soft)', borderRadius: 'var(--radius-card)',
        padding: '10px 14px', marginBottom: 14,
      }}
    >
      <AlertTriangle size={14} strokeWidth={1.75} color="var(--color-gold)" style={{ flexShrink: 0, marginTop: 2 }} />
      <div style={{ fontSize: 12.5, color: 'var(--color-ink-700)', lineHeight: 1.5 }}>
        {shown.map((s) => (
          <div key={s.source}>
            <strong>{s.source}:</strong> {s.items.join(', ')} could not be measured in time — shown as “—”.
          </div>
        ))}
      </div>
    </div>
  )
}
