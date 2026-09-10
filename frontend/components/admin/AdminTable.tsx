'use client'
import { ChevronLeft, ChevronRight } from 'lucide-react'

/* Shared table styling for the admin pages — same house style as
   components/LeadTable.tsx (TH_STYLE + zebra rows + prev/next footer). */

export const TH_STYLE: React.CSSProperties = {
  textAlign: 'left',
  padding: '10px 14px',
  fontSize: 11,
  fontWeight: 600,
  letterSpacing: '0.08em',
  textTransform: 'uppercase',
  color: 'var(--color-ink-500)',
  whiteSpace: 'nowrap',
  borderBottom: '1px solid var(--color-ink-200)',
}

export const TD_STYLE: React.CSSProperties = {
  padding: '10px 14px',
  fontSize: 13,
  color: 'var(--color-ink-800)',
  borderBottom: '1px solid var(--color-ink-100)',
  verticalAlign: 'middle',
}

export function zebra(i: number): string {
  return i % 2 === 0 ? 'var(--color-surface)' : 'transparent'
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

export function Pagination({
  total, page, pageSize, noun, onPage,
}: {
  total: number
  page: number
  pageSize: number
  noun: string
  onPage: (page: number) => void
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const btn = (disabled: boolean): React.CSSProperties => ({
    width: 44, height: 44, display: 'flex', alignItems: 'center', justifyContent: 'center',
    background: 'none', border: 'none', cursor: disabled ? 'default' : 'pointer',
    color: 'var(--color-ink-700)', opacity: disabled ? 0.35 : 1,
  })
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 2px' }}>
      <span style={{ fontSize: 12.5, color: 'var(--color-ink-500)' }}>
        {total.toLocaleString()} {noun}
      </span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
        <button style={btn(page <= 1)} disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page">
          <ChevronLeft size={16} strokeWidth={1.5} />
        </button>
        <span className="tabular" style={{ fontSize: 12.5, color: 'var(--color-ink-600)' }}>
          {page} / {totalPages}
        </span>
        <button style={btn(page >= totalPages)} disabled={page >= totalPages} onClick={() => onPage(page + 1)} aria-label="Next page">
          <ChevronRight size={16} strokeWidth={1.5} />
        </button>
      </div>
    </div>
  )
}

/** "42s", "3m 05s", "1h 12m" — a job or run's wall time; "—" when unknown. */
export function fmtDuration(s: number | null | undefined): string {
  if (s === null || s === undefined || Number.isNaN(s)) return '—'
  const secs = Math.max(0, Math.round(s))
  if (secs < 60) return `${secs}s`
  const m = Math.floor(secs / 60)
  if (m < 60) return `${m}m ${String(secs % 60).padStart(2, '0')}s`
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`
}

/* Card chrome + a titled table inside it — the Security and Ops pages' section
   unit, kept here so there is one copy of the style. */

export const CARD: React.CSSProperties = {
  background: 'var(--color-surface)', borderRadius: 'var(--radius-card)',
  boxShadow: 'var(--shadow-card)', marginBottom: 18,
}

export function SectionTable({ title, headers, empty, note, children }: {
  title: string
  headers: string[]
  empty: boolean
  note?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div style={{ ...CARD, overflowX: 'auto' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap', padding: '14px 16px 8px' }}>
        <h2 className="t-eyebrow" style={{ margin: 0 }}>{title}</h2>
        {note && <span style={{ fontSize: 12.5, color: 'var(--color-ink-500)' }}>{note}</span>}
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>{headers.map((h, i) => <th key={`${h}-${i}`} style={TH_STYLE}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {empty && (
            <tr><td colSpan={headers.length} style={{ ...TD_STYLE, textAlign: 'center', padding: '24px 0', color: 'var(--color-ink-400)' }}>Nothing to show</td></tr>
          )}
          {children}
        </tbody>
      </table>
    </div>
  )
}
