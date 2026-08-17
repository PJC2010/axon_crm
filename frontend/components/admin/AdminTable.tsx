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
