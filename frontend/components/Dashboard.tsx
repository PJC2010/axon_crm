'use client'
import { useEffect, useState, useCallback } from 'react'
import { RefreshCw, AlertCircle, Kanban, CheckSquare, Settings, LogOut, Receipt, BookOpen, Home, Menu, X } from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { getLeads } from '@/lib/api'
import { clearToken } from '@/lib/auth'
import type { Lead, LeadFilters, LeadStatus } from '@/lib/types'
import { LeadTable } from './LeadTable'
import { TerritoryFilter } from './TerritoryFilter'
import { ContactDrawer } from './ContactDrawer'
import { ExportButton } from './ExportButton'
import { ImportContactsModal } from './ImportContactsModal'
import { TaskBell } from './TaskBell'
import { ToastStack, useToast } from './Toast'

const DEFAULT_FILTERS: LeadFilters = { sort: 'score', page: 1, page_size: 50 }

export function Dashboard() {
  const router = useRouter()
  const [filters, setFilters]   = useState<LeadFilters>(DEFAULT_FILTERS)
  const [leads, setLeads]       = useState<Lead[]>([])
  const [total, setTotal]       = useState(0)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState<string | null>(null)
  const [selected, setSelected] = useState<Lead | null>(null)
  const [wide, setWide]         = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const { toasts, show: showToast, dismiss: dismissToast } = useToast()

  useEffect(() => {
    const check = () => {
      const w = window.innerWidth >= 640
      setWide(w)
      if (w) setMenuOpen(false)
    }
    check()
    window.addEventListener('resize', check)
    return () => window.removeEventListener('resize', check)
  }, [])

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
          padding: wide ? '0 28px' : '0 16px',
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
            <svg width="26" height="26" viewBox="0 0 32 32" fill="none" aria-hidden="true">
              <mask id="axon-mark-dash">
                <rect width="32" height="32" fill="white" />
                <rect x="2" y="14.5" width="28" height="3" rx="1.5" fill="black" />
                <rect x="14.5" y="2" width="3" height="28" rx="1.5" fill="black" />
              </mask>
              <polygon points="16,5 27,16 16,27 5,16" fill="var(--color-accent)" mask="url(#axon-mark-dash)" />
              <circle cx="16" cy="16" r="1.5" fill="var(--color-ink-900)" />
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
          <span className="t-eyebrow">{wide ? 'Lead dashboard' : 'Leads'}</span>
        </div>

        {wide ? (
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
            <ImportContactsModal onImported={() => fetchLeads(filters)} />
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
        ) : (
          <div className="flex items-center gap-1">
            <TaskBell />
            <button
              onClick={() => fetchLeads(filters)}
              title="Refresh"
              className="dash-icon-btn"
            >
              <RefreshCw size={13} strokeWidth={1.5} className={loading ? 'animate-spin' : ''} />
            </button>
            <button
              onClick={() => setMenuOpen(o => !o)}
              className="dash-icon-btn"
              title="Menu"
              aria-label={menuOpen ? 'Close menu' : 'Open menu'}
              aria-expanded={menuOpen}
            >
              {menuOpen ? <X size={16} strokeWidth={1.5} /> : <Menu size={16} strokeWidth={1.5} />}
            </button>
          </div>
        )}
      </header>

      {/* ── Mobile Nav Menu ── */}
      {!wide && menuOpen && (
        <>
          <div
            onClick={() => setMenuOpen(false)}
            style={{ position: 'fixed', inset: 0, zIndex: 19, background: 'rgba(22,24,29,0.18)' }}
          />
          <nav style={{
            position: 'fixed', top: 64, left: 0, right: 0, zIndex: 20,
            background: 'var(--color-surface)',
            borderBottom: '1px solid var(--color-ink-200)',
            boxShadow: 'var(--shadow-pop)',
            padding: 8,
            display: 'flex', flexDirection: 'column', gap: 2,
          }}>
            {[
              { label: 'Home',        icon: <Home size={18} strokeWidth={1.5} color="var(--color-ink-500)" />,        href: '/home' },
              { label: 'Pipeline',    icon: <Kanban size={18} strokeWidth={1.5} color="var(--color-ink-500)" />,      href: '/pipeline' },
              { label: 'Tasks',       icon: <CheckSquare size={18} strokeWidth={1.5} color="var(--color-ink-500)" />, href: '/tasks' },
              { label: 'Expenses',    icon: <Receipt size={18} strokeWidth={1.5} color="var(--color-ink-500)" />,     href: '/expenses' },
              { label: 'Bookkeeping', icon: <BookOpen size={18} strokeWidth={1.5} color="var(--color-ink-500)" />,    href: '/bookkeeping' },
              { label: 'Settings',    icon: <Settings size={18} strokeWidth={1.5} color="var(--color-ink-500)" />,    href: '/settings' },
            ].map(({ label, icon, href }) => (
              <Link
                key={href}
                href={href}
                onClick={() => setMenuOpen(false)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 12,
                  padding: '12px 14px', minHeight: 48,
                  borderRadius: 'var(--radius-button)',
                  textDecoration: 'none', color: 'var(--color-ink-800)',
                  fontSize: 15, fontWeight: 500,
                }}
              >
                {icon}
                {label}
              </Link>
            ))}

            {/* Lead actions */}
            <div style={{ borderTop: '1px solid var(--color-ink-100)', margin: '6px 0', paddingTop: 10 }}>
              <p className="t-eyebrow" style={{ margin: '0 0 8px', padding: '0 14px' }}>Lead actions</p>
              <div onClick={() => setMenuOpen(false)} style={{ display: 'flex', flexWrap: 'wrap', gap: 8, padding: '0 14px' }}>
                <ImportContactsModal onImported={() => fetchLeads(filters)} />
                <ExportButton filters={filters} />
              </div>
            </div>

            <button
              onClick={() => { setMenuOpen(false); handleSignOut() }}
              style={{
                display: 'flex', alignItems: 'center', gap: 12,
                padding: '12px 14px', minHeight: 48, width: '100%',
                borderRadius: 'var(--radius-button)',
                border: 'none', background: 'transparent', cursor: 'pointer',
                color: 'var(--color-danger)', fontSize: 15, fontWeight: 500, textAlign: 'left',
              }}
            >
              <LogOut size={18} strokeWidth={1.5} />
              Sign out
            </button>
          </nav>
        </>
      )}

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
          onToast={showToast}
        />
      </main>

      <ContactDrawer
        lead={selected}
        onClose={() => setSelected(null)}
        onStatusChange={handleStatusChange}
      />

      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </div>
  )
}
