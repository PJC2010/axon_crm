'use client'
import { useState } from 'react'
import { ChevronLeft, ChevronRight, Search, Settings, Archive, MoreVertical } from 'lucide-react'
import Link from 'next/link'
import type { Lead, LeadFilters, LeadStatus } from '@/lib/types'
import { archiveBulk, archiveByFilter } from '@/lib/api'
import { ConfirmModal } from './ConfirmModal'
import { useTerminology } from '@/hooks/useTerminology'
import { resolveLeadColumns } from './lead/leadColumns'

interface Props {
  leads: Lead[]
  total: number
  filters: LeadFilters
  loading: boolean
  onRowClick: (lead: Lead) => void
  onFiltersChange: (f: LeadFilters) => void
  onStatusChange: (id: number, s: LeadStatus) => void
  onToast?: (msg: string, variant?: 'success' | 'error') => void
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

export function LeadTable({ leads, total, filters, loading, onRowClick, onFiltersChange, onStatusChange, onToast }: Props) {
  const { t, listColumns, categories, propertyBased } = useTerminology()
  const columns = resolveLeadColumns(listColumns, { t, categories, propertyBased })
  const page      = filters.page ?? 1
  const pageSize  = filters.page_size ?? PAGE_SIZE
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [archiving, setArchiving] = useState(false)
  const [showBulkMenu, setShowBulkMenu] = useState(false)
  const [confirmArchiveAll, setConfirmArchiveAll] = useState(false)

  const toggleSelect = (id: number) => {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelected(next)
  }

  const toggleSelectAll = () => {
    if (selected.size === leads.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(leads.map(l => l.id)))
    }
  }

  async function handleArchiveSelected() {
    if (selected.size === 0) return
    setArchiving(true)
    try {
      await archiveBulk(Array.from(selected))
      setSelected(new Set())
      onFiltersChange(filters)
      onToast?.(`Archived ${selected.size} ${(selected.size !== 1 ? t('leads') : t('lead')).toLowerCase()}`)
    } catch {
      onToast?.('Archive failed — please try again', 'error')
    } finally { setArchiving(false) }
  }

  async function handleArchiveAll() {
    setArchiving(true)
    try {
      await archiveByFilter(filters)
      setSelected(new Set())
      onFiltersChange(filters)
      onToast?.(`Archived all ${total} matching ${t('leads').toLowerCase()}`)
    } catch {
      onToast?.('Archive failed — please try again', 'error')
    } finally {
      setArchiving(false)
      setConfirmArchiveAll(false)
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Bulk action toolbar */}
      {selected.size > 0 && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 12,
          padding: '12px 16px', background: 'var(--color-accent)', color: 'white',
          fontSize: 13, borderBottom: '1px solid var(--color-ink-200)',
        }}>
          <span style={{ flex: 1 }}>{selected.size} of {leads.length} selected</span>
          <div style={{ position: 'relative' }}>
            <button
              onClick={() => setShowBulkMenu(!showBulkMenu)}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 6,
                padding: '6px 14px', background: 'rgba(255,255,255,0.2)', border: 'none',
                borderRadius: 'var(--radius-pill)', color: 'white', fontSize: 12, fontWeight: 500,
                cursor: 'pointer',
              }}
            >
              <Archive size={12} strokeWidth={1.5} /> Archive
              <MoreVertical size={12} strokeWidth={1.5} />
            </button>
            {showBulkMenu && (
              <div style={{
                position: 'absolute', top: '100%', right: 0, marginTop: 4,
                background: 'var(--color-surface)', border: '1px solid var(--color-ink-200)',
                borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)',
                zIndex: 100, minWidth: 200,
              }}>
                <button
                  onClick={handleArchiveSelected}
                  disabled={archiving}
                  style={{
                    display: 'block', width: '100%', textAlign: 'left', padding: '10px 14px',
                    background: 'none', border: 'none', color: 'var(--color-ink-900)',
                    fontSize: 13, cursor: archiving ? 'not-allowed' : 'pointer',
                    borderBottom: '1px solid var(--color-ink-100)',
                  }}
                >
                  Archive {selected.size} selected
                </button>
                <button
                  onClick={() => { setShowBulkMenu(false); setConfirmArchiveAll(true) }}
                  disabled={archiving}
                  style={{
                    display: 'block', width: '100%', textAlign: 'left', padding: '10px 14px',
                    background: 'none', border: 'none', color: 'var(--color-ink-900)',
                    fontSize: 13, cursor: archiving ? 'not-allowed' : 'pointer',
                  }}
                >
                  Archive all {total} matching filters
                </button>
              </div>
            )}
          </div>
          <button
            onClick={() => setSelected(new Set())}
            style={{
              background: 'none', border: 'none', color: 'white', fontSize: 12,
              cursor: 'pointer', textDecoration: 'underline',
            }}
          >
            Clear
          </button>
        </div>
      )}

      <div className="flex-1 overflow-auto">
        <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-sans)' }}>
          <thead>
            <tr style={{ background: 'var(--color-paper)', position: 'sticky', top: 0, zIndex: 10 }}>
              <th style={{ ...TH_STYLE, width: 32, padding: '10px 8px', textAlign: 'center' }}>
                <input
                  type="checkbox"
                  checked={selected.size > 0 && selected.size === leads.length}
                  onChange={toggleSelectAll}
                  style={{ cursor: 'pointer' }}
                />
              </th>
              {columns.map(col => (
                <th key={col.key} style={TH_STYLE}>{col.header}</th>
              ))}
              <th style={TH_STYLE} aria-hidden />

            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={columns.length + 2} style={{ textAlign: 'center', padding: '64px 0', fontSize: 13, color: 'var(--color-ink-400)' }}>
                  Loading…
                </td>
              </tr>
            )}
            {!loading && leads.length === 0 && total === 0 && (
              <tr>
                <td colSpan={columns.length + 2} style={{ textAlign: 'center', padding: '64px 20px' }}>
                  <Search size={48} strokeWidth={1} style={{ color: 'var(--color-ink-300)', marginBottom: 12 }} />
                  <p style={{ margin: '0 0 6px', fontSize: 16, fontWeight: 600, color: 'var(--color-ink-700)' }}>No leads yet</p>
                  <p style={{ margin: '0 0 16px', fontSize: 13, color: 'var(--color-ink-400)', maxWidth: 320, marginLeft: 'auto', marginRight: 'auto' }}>
                    Run the pipeline to import leads from your target area and start scoring them.
                  </p>
                  <Link href="/settings" style={{
                    display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 20px',
                    borderRadius: 'var(--radius-pill)', background: 'var(--color-accent)', color: 'white',
                    fontSize: 13, fontWeight: 500, textDecoration: 'none',
                  }}>
                    <Settings size={14} strokeWidth={1.5} /> Go to Settings
                  </Link>
                </td>
              </tr>
            )}
            {!loading && leads.length === 0 && total > 0 && (
              <tr>
                <td colSpan={columns.length + 2} style={{ textAlign: 'center', padding: '64px 0', fontSize: 13, color: 'var(--color-ink-400)' }}>
                  No leads match the current filters.
                </td>
              </tr>
            )}
            {!loading && leads.map((lead, i) => (
              <tr
                key={lead.id}
                onClick={() => onRowClick(lead)}
                style={{
                  background: i % 2 === 0 ? 'var(--color-surface)' : 'transparent',
                  borderBottom: '1px solid var(--color-ink-100)',
                  cursor: 'pointer',
                  transition: 'background 120ms',
                }}
                onMouseEnter={e => (e.currentTarget as HTMLTableRowElement).style.background = 'var(--color-surface-hi)'}
                onMouseLeave={e => (e.currentTarget as HTMLTableRowElement).style.background = i % 2 === 0 ? 'var(--color-surface)' : 'transparent'}
              >
                <td style={{ padding: '8px', width: 32, textAlign: 'center' }} onClick={e => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={selected.has(lead.id)}
                    onChange={() => toggleSelect(lead.id)}
                    style={{ cursor: 'pointer' }}
                  />
                </td>
                {columns.map(col => (
                  <td
                    key={col.key}
                    className={col.cellClassName}
                    style={{ padding: '12px 14px', fontSize: 13.5, color: 'var(--color-ink-800)', ...col.cellStyle }}
                    onClick={col.stopPropagation ? e => e.stopPropagation() : undefined}
                  >
                    {col.render(lead, { onStatusChange })}
                  </td>
                ))}
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
          background: 'var(--color-surface)',
          fontSize: 12,
          color: 'var(--color-ink-500)',
          flexShrink: 0,
        }}
      >
        <span>{total.toLocaleString()} leads</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <button
            onClick={() => onFiltersChange({ ...filters, page: page - 1 })}
            disabled={page <= 1}
            aria-label="Previous page"
            style={{
              width: 40, height: 40,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              borderRadius: 'var(--radius-button)',
              border: '1px solid var(--color-ink-200)',
              background: 'var(--color-surface)',
              cursor: page <= 1 ? 'not-allowed' : 'pointer',
              opacity: page <= 1 ? 0.35 : 1,
              color: 'var(--color-ink-700)',
              transition: 'border-color 150ms, background 150ms',
            }}
          >
            <ChevronLeft size={15} strokeWidth={1.5} />
          </button>
          <span className="tabular" style={{ padding: '0 8px', whiteSpace: 'nowrap' }}>
            {page} / {totalPages}
          </span>
          <button
            onClick={() => onFiltersChange({ ...filters, page: page + 1 })}
            disabled={page >= totalPages}
            aria-label="Next page"
            style={{
              width: 40, height: 40,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              borderRadius: 'var(--radius-button)',
              border: '1px solid var(--color-ink-200)',
              background: 'var(--color-surface)',
              cursor: page >= totalPages ? 'not-allowed' : 'pointer',
              opacity: page >= totalPages ? 0.35 : 1,
              color: 'var(--color-ink-700)',
              transition: 'border-color 150ms, background 150ms',
            }}
          >
            <ChevronRight size={15} strokeWidth={1.5} />
          </button>
        </div>
      </div>

      {confirmArchiveAll && (
        <ConfirmModal
          title="Archive all matching leads?"
          message={`This will archive all ${total.toLocaleString()} leads that match your current filters. You can restore them later from Settings.`}
          confirmLabel={`Archive ${total.toLocaleString()} leads`}
          danger
          loading={archiving}
          onConfirm={handleArchiveAll}
          onCancel={() => setConfirmArchiveAll(false)}
        />
      )}
    </div>
  )
}
