'use client'
import { useEffect, useState, useCallback } from 'react'
import { RefreshCw, AlertCircle } from 'lucide-react'
import { getLeads } from '@/lib/api'
import type { Lead, LeadFilters, LeadStatus } from '@/lib/types'
import { LeadTable } from './LeadTable'
import { TerritoryFilter } from './TerritoryFilter'
import { ContactDrawer } from './ContactDrawer'
import { ExportButton } from './ExportButton'

const DEFAULT_FILTERS: LeadFilters = { sort: 'score', page: 1, page_size: 50 }

export function Dashboard() {
  const [filters, setFilters]   = useState<LeadFilters>(DEFAULT_FILTERS)
  const [leads, setLeads]       = useState<Lead[]>([])
  const [total, setTotal]       = useState(0)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState<string | null>(null)
  const [selected, setSelected] = useState<Lead | null>(null)

  const fetchLeads = useCallback(async (f: LeadFilters) => {
    setLoading(true)
    setError(null)
    try {
      const page = await getLeads(f)
      setLeads(page.results)
      setTotal(page.total)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load leads')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchLeads(filters) }, [filters, fetchLeads])

  function handleStatusChange(id: number, status: LeadStatus) {
    setLeads(prev => prev.map(l => l.id === id ? { ...l, status } : l))
    if (selected?.id === id) setSelected(prev => prev ? { ...prev, status } : prev)
  }

  return (
    <div className="flex flex-col h-screen" style={{ background: 'var(--color-paper)' }}>
      {/* Top nav */}
      <header
        className="flex items-center justify-between shrink-0"
        style={{
          height: 64,
          padding: '0 28px',
          background: 'var(--color-paper)',
          borderBottom: '1px solid var(--color-ink-200)',
        }}
      >
        <div className="flex items-center gap-3">
          <span
            className="text-[22px] font-semibold tracking-tight"
            style={{ fontFamily: 'var(--font-display)', letterSpacing: '-0.01em', color: 'var(--color-ink-900)' }}
          >
            Smart CRM
          </span>
          <span style={{ color: 'var(--color-ink-300)', fontSize: 14 }}>·</span>
          <span className="t-eyebrow">Lead dashboard</span>
        </div>
        <div className="flex items-center gap-2">
          <ExportButton filters={filters} />
          <button
            onClick={() => fetchLeads(filters)}
            title="Refresh"
            style={{
              padding: '6px',
              borderRadius: 'var(--radius-button)',
              border: '1px solid var(--color-ink-200)',
              background: 'white',
              color: 'var(--color-ink-400)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              transition: 'color 180ms, border-color 180ms',
            }}
            onMouseEnter={e => {
              (e.currentTarget as HTMLButtonElement).style.color = 'var(--color-ink-900)'
              ;(e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--color-accent)'
            }}
            onMouseLeave={e => {
              (e.currentTarget as HTMLButtonElement).style.color = 'var(--color-ink-400)'
              ;(e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--color-ink-200)'
            }}
          >
            <RefreshCw size={13} strokeWidth={1.5} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </header>

      <TerritoryFilter filters={filters} onChange={f => setFilters({ ...f, page: 1 })} />

      {error && (
        <div
          className="mx-6 mt-4 flex items-center gap-2 text-sm"
          style={{
            padding: '10px 14px',
            borderRadius: 'var(--radius-card)',
            background: 'var(--color-danger-bg)',
            border: '1px solid color-mix(in srgb, var(--color-danger) 25%, transparent)',
            color: 'var(--color-danger)',
          }}
        >
          <AlertCircle size={14} strokeWidth={1.5} />
          {error} — is the API running?
          <code className="tabular text-xs ml-1">uvicorn api.main:app --reload</code>
        </div>
      )}

      <main className="flex-1 overflow-hidden">
        <LeadTable
          leads={leads}
          total={total}
          filters={filters}
          loading={loading}
          onRowClick={setSelected}
          onFiltersChange={setFilters}
          onStatusChange={handleStatusChange}
        />
      </main>

      <ContactDrawer
        lead={selected}
        onClose={() => setSelected(null)}
        onStatusChange={handleStatusChange}
      />
    </div>
  )
}
