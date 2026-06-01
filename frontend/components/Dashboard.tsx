'use client'
import { useEffect, useState, useCallback } from 'react'
import { RefreshCw, AlertCircle, Kanban, CheckSquare, Settings, LogOut, Receipt, BookOpen, Home } from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { getLeads } from '@/lib/api'
import { clearToken } from '@/lib/auth'
import type { Lead, LeadFilters, LeadStatus } from '@/lib/types'
import { LeadTable } from './LeadTable'
import { TerritoryFilter } from './TerritoryFilter'
import { ContactDrawer } from './ContactDrawer'
import { ExportButton } from './ExportButton'
import { TaskBell } from './TaskBell'

const DEFAULT_FILTERS: LeadFilters = { sort: 'score', page: 1, page_size: 50 }

export function Dashboard() {
  const router = useRouter()
  const [filters, setFilters]   = useState<LeadFilters>(DEFAULT_FILTERS)
  const [leads, setLeads]       = useState<Lead[]>([])
  const [total, setTotal]       = useState(0)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState<string | null>(null)
  const [selected, setSelected] = useState<Lead | null>(null)

  function handleSignOut() {
    clearToken()
    router.push('/login')
  }

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
      {/* Top nav — matches landing page nav height and token usage */}
      <header
        className="flex items-center justify-between shrink-0"
        style={{
          height: 64,
          padding: '0 28px',
          background: 'var(--color-paper)',
          borderBottom: '1px solid var(--color-ink-200)',
        }}
      >
        {/* Axon logo + wordmark — links back to landing */}
        <div className="flex items-center gap-3">
          <Link
            href="/"
            style={{ display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none', color: 'inherit' }}
          >
            <svg width="26" height="26" viewBox="0 0 40 40" fill="none">
              <path
                d="M4 32 C 12 32, 14 22, 22 22 C 30 22, 30 14, 38 6"
                stroke="var(--color-ink-900)" strokeWidth="2.5"
                strokeLinecap="round" strokeLinejoin="round"
              />
              <circle cx="4" cy="32" r="3" fill="var(--color-ink-900)" />
              <circle cx="22" cy="22" r="4" fill="var(--color-paper)" stroke="var(--color-ink-900)" strokeWidth="2.5" />
              <circle cx="38" cy="6" r="6" fill="var(--color-accent)" />
            </svg>
            <span style={{
              fontFamily: 'var(--font-display)',
              fontSize: 20,
              fontWeight: 600,
              letterSpacing: '-0.01em',
              color: 'var(--color-ink-900)',
            }}>
              Axon
            </span>
          </Link>
          <span style={{ color: 'var(--color-ink-300)', fontSize: 14 }}>·</span>
          <span className="t-eyebrow">Lead dashboard</span>
        </div>

        <div className="flex items-center gap-1">
          <Link href="/home" title="Home" className="dash-icon-btn" style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '0 10px', textDecoration: 'none', color: 'inherit', fontSize: 13 }}>
            <Home size={13} strokeWidth={1.5} />
            <span>Home</span>
          </Link>
          <Link href="/pipeline" title="Pipeline" className="dash-icon-btn" style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '0 10px', textDecoration: 'none', color: 'inherit', fontSize: 13 }}>
            <Kanban size={13} strokeWidth={1.5} />
            <span>Pipeline</span>
          </Link>
          <Link href="/tasks" title="Tasks" className="dash-icon-btn" style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '0 10px', textDecoration: 'none', color: 'inherit', fontSize: 13 }}>
            <CheckSquare size={13} strokeWidth={1.5} />
            <span>Tasks</span>
          </Link>
          <Link href="/expenses" title="Expenses" className="dash-icon-btn" style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '0 10px', textDecoration: 'none', color: 'inherit', fontSize: 13 }}>
            <Receipt size={13} strokeWidth={1.5} />
            <span>Expenses</span>
          </Link>
          <Link href="/bookkeeping" title="Bookkeeping" className="dash-icon-btn" style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '0 10px', textDecoration: 'none', color: 'inherit', fontSize: 13 }}>
            <BookOpen size={13} strokeWidth={1.5} />
            <span>Books</span>
          </Link>
          <TaskBell />
          <ExportButton filters={filters} />
          <button
            onClick={() => fetchLeads(filters)}
            title="Refresh"
            className="dash-icon-btn"
          >
            <RefreshCw size={13} strokeWidth={1.5} className={loading ? 'animate-spin' : ''} />
          </button>
          <Link href="/settings" title="Settings" className="dash-icon-btn">
            <Settings size={13} strokeWidth={1.5} />
          </Link>
          <button onClick={handleSignOut} title="Sign out" className="dash-icon-btn">
            <LogOut size={13} strokeWidth={1.5} />
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
