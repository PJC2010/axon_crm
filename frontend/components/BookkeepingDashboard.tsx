'use client'
import { useEffect, useState } from 'react'
import { BookOpen, ChevronDown, Home } from 'lucide-react'
import Link from 'next/link'
import { BookkeepingOverview } from './BookkeepingOverview'
import { InvoiceList } from './InvoiceList'
import { QuoteList } from './QuoteList'
import { ARDashboard } from './ARDashboard'
import { PnLChart } from './PnLChart'
import { JobCostingTable } from './JobCostingTable'
import { ToastStack, useToast } from './Toast'
import { getLead } from '@/lib/api'
import type { Lead } from '@/lib/types'

type Tab = 'overview' | 'quotes' | 'invoices' | 'ar' | 'pnl' | 'jobs'

const TABS: { id: Tab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'quotes',   label: 'Quotes' },
  { id: 'invoices', label: 'Invoices' },
  { id: 'ar',       label: 'A/R' },
  { id: 'pnl',      label: 'P&L' },
  { id: 'jobs',     label: 'Job Costing' },
]

const THIS_YEAR = new Date().getFullYear()
const YEAR_OPTIONS = Array.from({ length: 5 }, (_, i) => THIS_YEAR - i)

interface Props {
  /** Deep-link support: ?tab=quotes&lead=123 opens the quote builder prefilled. */
  initialTab?: Tab
  quoteLeadId?: number
}

export function BookkeepingDashboard({ initialTab, quoteLeadId }: Props = {}) {
  const [tab, setTab]   = useState<Tab>(initialTab ?? 'overview')
  const [year, setYear] = useState(THIS_YEAR)
  const [prefillLead, setPrefillLead] = useState<Lead | null>(null)
  const [leadLoaded, setLeadLoaded] = useState(!quoteLeadId)
  const { toasts, show: showToast, dismiss: dismissToast } = useToast()

  useEffect(() => {
    if (!quoteLeadId) return
    let cancelled = false
    getLead(quoteLeadId)
      .then(lead => { if (!cancelled) setPrefillLead(lead) })
      .catch(() => {}) // missing lead → plain quotes tab
      .finally(() => { if (!cancelled) setLeadLoaded(true) })
    return () => { cancelled = true }
  }, [quoteLeadId])

  return (
    <div style={{ minHeight: '100dvh', background: 'var(--color-paper)' }}>
      {/* Header */}
      <header style={{
        height: 64, padding: '0 20px', display: 'flex', alignItems: 'center',
        justifyContent: 'space-between', gap: 12,
        borderBottom: '1px solid var(--color-ink-200)',
        background: 'var(--color-paper)', position: 'sticky', top: 0, zIndex: 10,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Link href="/home" title="Home" className="dash-icon-btn" style={{ textDecoration: 'none', color: 'inherit' }}>
            <Home size={15} strokeWidth={1.5} />
          </Link>
          <BookOpen size={18} strokeWidth={1.5} color="var(--color-accent)" />
          <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 600, color: 'var(--color-ink-900)', margin: 0 }}>
            Bookkeeping
          </h1>
        </div>

        {/* Year selector */}
        <div style={{ position: 'relative' }}>
          <select value={year} onChange={e => setYear(Number(e.target.value))} className="select-field" style={{ paddingRight: 28, appearance: 'none', fontWeight: 600 }}>
            {YEAR_OPTIONS.map(y => <option key={y} value={y}>{y}</option>)}
          </select>
          <ChevronDown size={12} style={{ position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none', color: 'var(--color-ink-500)' }} />
        </div>
      </header>

      {/* Tab nav — horizontally scrollable on mobile */}
      <div style={{
        borderBottom: '1px solid var(--color-ink-200)',
        background: 'var(--color-paper)',
        position: 'sticky', top: 64, zIndex: 9,
        overflowX: 'auto',
      }}>
        <div style={{ display: 'flex', padding: '0 20px', gap: 0, minWidth: 'max-content' }}>
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              style={{
                padding: '14px 18px', fontSize: 13, fontWeight: tab === t.id ? 600 : 400,
                color: tab === t.id ? 'var(--color-accent)' : 'var(--color-ink-500)',
                background: 'transparent', border: 'none', cursor: 'pointer',
                borderBottom: tab === t.id ? '2px solid var(--color-accent)' : '2px solid transparent',
                marginBottom: -1, whiteSpace: 'nowrap',
              }}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div style={{ maxWidth: 760, margin: '0 auto', padding: '24px 16px 48px' }}>
        {tab === 'overview' && <BookkeepingOverview year={year} />}
        {tab === 'quotes'   && leadLoaded && <QuoteList prefillLead={prefillLead} onToast={showToast} />}
        {tab === 'invoices' && <InvoiceList year={year} />}
        {tab === 'ar'       && <ARDashboard year={year} />}
        {tab === 'pnl'      && <PnLChart year={year} />}
        {tab === 'jobs'     && <JobCostingTable year={year} />}
      </div>

      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </div>
  )
}
