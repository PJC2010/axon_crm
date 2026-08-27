'use client'
import Link from 'next/link'
import { Check, ArrowRight } from 'lucide-react'

/**
 * "Try these" progress chips for the /preview demo — a tiny scavenger hunt
 * that nudges visitors into the interactions worth feeling (drag a deal, open
 * a score, add a lead) instead of scrolling past a static screenshot.
 */
export type TryKey = 'drag' | 'open' | 'status' | 'add' | 'map'

export const TRY_ITEMS: { key: TryKey; label: string }[] = [
  { key: 'drag',   label: 'Drag a deal on the board' },
  { key: 'open',   label: 'Open a lead’s score' },
  { key: 'status', label: 'Change a status' },
  { key: 'add',    label: 'Add your own lead' },
  { key: 'map',    label: 'Visit the map' },
]

export function TryChecklist({ done }: { done: Set<TryKey> }) {
  const allDone = TRY_ITEMS.every(i => done.has(i.key))
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, overflowX: 'auto', paddingBottom: 4 }}>
      <span className="t-eyebrow" style={{ whiteSpace: 'nowrap', flexShrink: 0 }}>
        Try it · {done.size}/{TRY_ITEMS.length}
      </span>
      {TRY_ITEMS.map(item => {
        const isDone = done.has(item.key)
        return (
          <span
            key={item.key}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '5px 12px', borderRadius: 'var(--radius-pill)', whiteSpace: 'nowrap',
              fontSize: 12, fontWeight: 500,
              background: isDone ? 'var(--color-success-bg)' : 'var(--color-surface)',
              border: `1px solid ${isDone ? 'var(--color-success)' : 'var(--color-ink-200)'}`,
              color: isDone ? 'var(--color-success)' : 'var(--color-ink-600)',
              transition: 'background 0.2s, border-color 0.2s, color 0.2s',
            }}
          >
            <span
              aria-hidden
              style={{
                width: 14, height: 14, borderRadius: '50%', flexShrink: 0,
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                background: isDone ? 'var(--color-success)' : 'transparent',
                border: isDone ? 'none' : '1.5px solid var(--color-ink-300)',
              }}
            >
              {isDone && <Check size={9} strokeWidth={3} color="white" />}
            </span>
            {item.label}
          </span>
        )
      })}
      {allDone && (
        <Link
          href="/signup"
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '5px 14px', borderRadius: 'var(--radius-pill)', whiteSpace: 'nowrap',
            fontSize: 12, fontWeight: 700, textDecoration: 'none',
            background: 'var(--color-accent)', color: 'var(--text-on-accent)',
          }}
        >
          You&apos;ve got the hang of it — start free <ArrowRight size={12} strokeWidth={2} />
        </Link>
      )}
    </div>
  )
}
