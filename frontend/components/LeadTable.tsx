'use client'
import { ChevronLeft, ChevronRight, Home } from 'lucide-react'
import type { Lead, LeadFilters, LeadStatus } from '@/lib/types'
import { ScoreBadge } from './ScoreBadge'
import { StatusSelect } from './StatusSelect'

interface Props {
  leads: Lead[]
  total: number
  filters: LeadFilters
  loading: boolean
  onRowClick: (lead: Lead) => void
  onFiltersChange: (f: LeadFilters) => void
  onStatusChange: (id: number, s: LeadStatus) => void
}

function fmt(d: string | null) {
  if (!d) return '—'
  return new Date(d).toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
}
function fmtCurrency(n: number | null) {
  if (n == null) return '—'
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000)     return `$${(n / 1_000).toFixed(0)}K`
  return `$${n}`
}

const PAGE_SIZE = 50

const TH_STYLE: React.CSSProperties = {
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

export function LeadTable({ leads, total, filters, loading, onRowClick, onFiltersChange, onStatusChange }: Props) {
  const page      = filters.page ?? 1
  const pageSize  = filters.page_size ?? PAGE_SIZE
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-auto">
        <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-sans)' }}>
          <thead>
            <tr style={{ background: 'var(--color-paper)', position: 'sticky', top: 0, zIndex: 10 }}>
              {['Address', 'Score', 'Year built', 'Equity', 'Garage', 'Last sale', 'Status', ''].map(h => (
                <th key={h} style={TH_STYLE}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={8} style={{ textAlign: 'center', padding: '64px 0', fontSize: 13, color: 'var(--color-ink-400)' }}>
                  Loading…
                </td>
              </tr>
            )}
            {!loading && leads.length === 0 && (
              <tr>
                <td colSpan={8} style={{ textAlign: 'center', padding: '64px 0', fontSize: 13, color: 'var(--color-ink-400)' }}>
                  No leads match the current filters.
                </td>
              </tr>
            )}
            {!loading && leads.map((lead, i) => (
              <tr
                key={lead.id}
                onClick={() => onRowClick(lead)}
                style={{
                  background: i % 2 === 0 ? 'white' : 'var(--color-paper)',
                  borderBottom: '1px solid var(--color-ink-100)',
                  cursor: 'pointer',
                  transition: 'background 120ms',
                }}
                onMouseEnter={e => (e.currentTarget as HTMLTableRowElement).style.background = 'var(--color-cream)'}
                onMouseLeave={e => (e.currentTarget as HTMLTableRowElement).style.background = i % 2 === 0 ? 'white' : 'var(--color-paper)'}
              >
                <td style={{ padding: '12px 14px', maxWidth: 240 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Home size={13} strokeWidth={1.5} style={{ color: 'var(--color-ink-300)', flexShrink: 0 }} />
                    <div>
                      <p style={{ fontWeight: 500, color: 'var(--color-ink-900)', fontSize: 13.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {lead.address}
                      </p>
                      <p style={{ fontSize: 11, color: 'var(--color-ink-500)', marginTop: 1 }}>
                        {[lead.city, lead.state, lead.zip].filter(Boolean).join(', ')}
                      </p>
                    </div>
                  </div>
                </td>
                <td style={{ padding: '12px 14px', whiteSpace: 'nowrap' }}>
                  <ScoreBadge grade={lead.score_grade} score={lead.lead_score} />
                </td>
                <td className="tabular" style={{ padding: '12px 14px', fontSize: 13.5, color: 'var(--color-ink-800)' }}>
                  {lead.year_built ?? '—'}
                </td>
                <td className="tabular" style={{ padding: '12px 14px', fontSize: 13.5, color: 'var(--color-ink-800)' }}>
                  {fmtCurrency(lead.estimated_equity)}
                </td>
                <td className="tabular" style={{ padding: '12px 14px', fontSize: 13.5, color: 'var(--color-ink-800)' }}>
                  {lead.garage_spaces != null ? `${lead.garage_spaces}-car` : '—'}
                </td>
                <td className="tabular" style={{ padding: '12px 14px', fontSize: 13.5, color: 'var(--color-ink-800)', whiteSpace: 'nowrap' }}>
                  {fmt(lead.last_sale_date)}
                </td>
                <td style={{ padding: '12px 14px' }} onClick={e => e.stopPropagation()}>
                  <StatusSelect leadId={lead.id} value={lead.status} onChange={s => onStatusChange(lead.id, s)} />
                </td>
                <td style={{ padding: '12px 14px', color: 'var(--color-ink-300)' }}>
                  <ChevronRight size={14} strokeWidth={1.5} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination footer */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '10px 20px',
          borderTop: '1px solid var(--color-ink-200)',
          background: 'white',
          fontSize: 12,
          color: 'var(--color-ink-500)',
          flexShrink: 0,
        }}
      >
        <span>{total.toLocaleString()} leads</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            onClick={() => onFiltersChange({ ...filters, page: page - 1 })}
            disabled={page <= 1}
            style={{
              padding: 4,
              borderRadius: 4,
              border: 'none',
              background: 'transparent',
              cursor: page <= 1 ? 'not-allowed' : 'pointer',
              opacity: page <= 1 ? 0.3 : 1,
              color: 'var(--color-ink-700)',
              display: 'flex',
            }}
          >
            <ChevronLeft size={14} strokeWidth={1.5} />
          </button>
          <span className="tabular">Page {page} of {totalPages}</span>
          <button
            onClick={() => onFiltersChange({ ...filters, page: page + 1 })}
            disabled={page >= totalPages}
            style={{
              padding: 4,
              borderRadius: 4,
              border: 'none',
              background: 'transparent',
              cursor: page >= totalPages ? 'not-allowed' : 'pointer',
              opacity: page >= totalPages ? 0.3 : 1,
              color: 'var(--color-ink-700)',
              display: 'flex',
            }}
          >
            <ChevronRight size={14} strokeWidth={1.5} />
          </button>
        </div>
      </div>
    </div>
  )
}
