'use client'
import { useEffect, useState, useCallback, type ReactNode } from 'react'
import {
  TrendingUp,
  Plus, FileText, Receipt, Kanban,
  AlertCircle, ArrowUpRight, ArrowDownRight,
  LogOut, Settings, ArrowRight,
  Percent, Target, Menu, X,
} from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { getMe, getTaskCounts, getPipelineStats, getARSummary, getLeads, getPipelineForecast, getPipelineAnalytics, getPnL, getExpenseSummary } from '@/lib/api'
import { clearToken } from '@/lib/auth'
import type { Lead, PipelineCounts, ARSummary, ForecastData, User, PipelineAnalytics, PnLReport, ExpenseSummary } from '@/lib/types'
import { ScoreBadge } from './ScoreBadge'
import { StatusPill } from './ds'
import { TaskBell } from './TaskBell'
import { NavLinks } from './NavLinks'
import { useEntitlements, clearEntitlementsCache } from '@/hooks/useEntitlements'
import { useTerminology } from '@/hooks/useTerminology'
import type { ModuleKey } from '@/lib/types'
import { OnboardingWizard } from './OnboardingWizard'
import { GettingStartedChecklist } from './GettingStartedChecklist'
import { ToastStack, useToast } from './Toast'
import { AIInsightsPanel } from './AIInsightsPanel'
import { PipelineRingChart } from './PipelineRingChart'
import { ActivityFeed } from './ActivityFeed'
import { TodayFocusSection } from './TodayFocusSection'
import { QuickAddFAB } from './QuickAddFAB'
import {
  useCountUp, Sparkline, CashflowBars, KpiTile, DrillDrawer, MONTH_ABBR,
  type CashflowDatum, type DrawerRow,
} from './home/dashboardKit'

const CLOSED_STAGES = new Set(['won', 'lost', 'not_interested'])

interface DashData {
  user: User | null
  taskCounts: PipelineCounts | null
  pipelineStats: Record<string, { count: number; total_value: number }> | null
  arSummary: ARSummary | null
  forecast: ForecastData | null
  analytics: PipelineAnalytics | null
  pnl: PnLReport | null
  expenses: ExpenseSummary | null
  recentLeads: Lead[]
}

function fmtCurrency(n: number): string {
  const sign = n < 0 ? '-' : ''
  const a = Math.abs(n)
  if (a >= 1_000_000) return `${sign}$${(a / 1_000_000).toFixed(1)}M`
  if (a >= 1_000)     return `${sign}$${(a / 1_000).toFixed(0)}k`
  return `${sign}$${a.toFixed(0)}`
}

function fmtFull(n: number): string {
  const sign = n < 0 ? '-' : ''
  return `${sign}$${Math.abs(Math.round(n)).toLocaleString('en-US')}`
}

type DrawerId = 'rev' | 'ar' | 'win' | 'forecast'

export function HomeDashboard() {
  const router = useRouter()
  const { hasModule } = useEntitlements()
  const { t } = useTerminology()
  const [data, setData] = useState<DashData>({
    user: null, taskCounts: null, pipelineStats: null, arSummary: null, forecast: null, analytics: null, pnl: null, expenses: null, recentLeads: [],
  })
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string | null>(null)
  const [wide, setWide]       = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [showOnboarding, setShowOnboarding] = useState(false)
  const [drawer, setDrawer]   = useState<DrawerId | null>(null)
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

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const year = new Date().getFullYear()
      const [userRes, countsRes, statsRes, arRes, forecastRes, analyticsRes, pnlRes, expRes, leadsRes] = await Promise.allSettled([
        getMe(),
        getTaskCounts(),
        getPipelineStats(),
        getARSummary(year),
        getPipelineForecast(),
        getPipelineAnalytics(30),
        getPnL(year),
        getExpenseSummary(year),
        getLeads({ sort: 'score', page: 1, page_size: 5 }),
      ])
      setData({
        user:          userRes.status      === 'fulfilled' ? userRes.value           : null,
        taskCounts:    countsRes.status    === 'fulfilled' ? countsRes.value         : null,
        pipelineStats: statsRes.status     === 'fulfilled' ? statsRes.value          : null,
        arSummary:     arRes.status        === 'fulfilled' ? arRes.value             : null,
        forecast:      forecastRes.status  === 'fulfilled' ? forecastRes.value       : null,
        analytics:     analyticsRes.status === 'fulfilled' ? analyticsRes.value      : null,
        pnl:           pnlRes.status       === 'fulfilled' ? pnlRes.value            : null,
        expenses:      expRes.status       === 'fulfilled' ? expRes.value            : null,
        recentLeads:   leadsRes.status     === 'fulfilled' ? leadsRes.value.results  : [],
      })
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load dashboard')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (data.user && !data.user.onboarding_complete) {
      setShowOnboarding(true)
    }
  }, [data.user])

  function handleSignOut() {
    clearToken()
    clearEntitlementsCache()
    router.push('/login')
  }

  const now      = new Date()
  const hour     = now.getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
  const dateStr  = now.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })
  const year     = now.getFullYear()

  const pipelineValue = data.pipelineStats
    ? Object.values(data.pipelineStats).reduce((s, v) => s + v.total_value, 0)
    : null

  const activeLeads = data.pipelineStats
    ? Object.entries(data.pipelineStats)
        .filter(([k]) => !CLOSED_STAGES.has(k))
        .reduce((s, [, v]) => s + v.count, 0)
    : null

  // ── Money-first derived values ──
  const netYTD      = data.pnl?.net_profit ?? null
  const collected   = data.arSummary?.total_collected ?? null
  const outstanding = data.arSummary?.total_outstanding ?? null
  const overdueAR   = data.arSummary?.total_overdue ?? 0
  const expensesYTD = data.pnl?.total_expenses ?? data.expenses?.total ?? null

  // This-month vs last-month, computed from the P&L months array.
  const curMonth    = now.getMonth() + 1
  const thisMonth   = data.pnl?.months.find(m => m.month === curMonth) ?? null
  const lastMonth   = data.pnl?.months.find(m => m.month === curMonth - 1) ?? null
  const monthNet    = thisMonth ? thisMonth.net : null
  const monthDelta  = thisMonth && lastMonth ? thisMonth.net - lastMonth.net : null
  const revThis     = thisMonth?.revenue ?? null
  const revDelta    = thisMonth && lastMonth ? thisMonth.revenue - lastMonth.revenue : null

  // ── Monthly series for charts/sparklines ──
  const monthsSorted = (data.pnl?.months ?? []).slice().sort((a, b) => a.month - b.month)
  const netSpark     = monthsSorted.map(m => m.net)
  const revenueSpark = monthsSorted.map(m => m.revenue).slice(-6)
  const cashflow: CashflowDatum[] = monthsSorted.map(m => ({ m: MONTH_ABBR[m.month - 1], inv: m.revenue, out: m.expenses }))
  const cashIn   = monthsSorted.reduce((s, m) => s + m.revenue, 0)
  const cashOut  = monthsSorted.reduce((s, m) => s + m.expenses, 0)

  const netAnim = useCountUp(netYTD ?? 0)

  if (showOnboarding) {
    return <OnboardingWizard onComplete={() => { setShowOnboarding(false); load() }} />
  }

  // ── Drill-down drawer content (progressive disclosure off each KPI tile) ──
  const drawerContent: Record<DrawerId, { eyebrow: string; title: string; rows: DrawerRow[]; cta: { label: string; href: string }; note?: string }> = {
    rev: {
      eyebrow: 'Sales', title: 'Revenue this month',
      rows: [
        { label: `This month (${MONTH_ABBR[curMonth - 1]})`, value: fmtFull(revThis ?? 0), tone: 'moss' },
        { label: 'Last month', value: fmtFull(lastMonth?.revenue ?? 0) },
        { label: 'Revenue · YTD', value: fmtFull(data.pnl?.total_revenue ?? 0) },
        { label: 'Net profit · YTD', value: fmtFull(netYTD ?? 0), tone: (netYTD ?? 0) >= 0 ? 'moss' : 'danger' },
      ],
      cta: { label: 'Open P&L report', href: '/bookkeeping' },
      note: 'Monthly revenue vs. expenses · drill into invoices from Bookkeeping',
    },
    ar: {
      eyebrow: 'Accounts Receivable', title: 'Outstanding invoices',
      rows: [
        { label: 'Collected', value: fmtFull(collected ?? 0), tone: 'moss' },
        { label: 'Outstanding', value: fmtFull(outstanding ?? 0) },
        { label: 'Overdue', value: fmtFull(overdueAR), tone: overdueAR > 0 ? 'danger' : 'muted' },
        { label: 'Open invoices', value: String(data.arSummary?.invoice_count ?? 0) },
      ],
      cta: { label: 'View invoices', href: '/bookkeeping' },
      note: 'Send reminders on overdue invoices to improve cash flow',
    },
    win: {
      eyebrow: 'Pipeline', title: 'Win rate · last 30 days',
      rows: [
        { label: 'Win rate', value: `${data.analytics?.win_rate ?? 0}%`, tone: 'moss' },
        { label: 'Deals won', value: String(data.analytics?.leads_won ?? 0) },
        { label: 'Avg cycle time', value: data.analytics?.avg_cycle_time != null ? `${data.analytics.avg_cycle_time}d` : '—' },
        { label: `Active ${t('leads').toLowerCase()}`, value: activeLeads != null ? String(activeLeads) : '—' },
      ],
      cta: { label: 'View pipeline', href: '/pipeline' },
    },
    forecast: {
      eyebrow: 'Forecast', title: 'Weighted pipeline',
      rows: (data.forecast?.by_stage ?? []).map(s => ({
        label: `${s.stage} · ${s.count}`, value: fmtFull(s.weighted_value),
      })),
      cta: { label: 'View pipeline', href: '/pipeline' },
      note: 'Open value weighted by stage win-probability',
    },
  }
  const dc = drawer ? drawerContent[drawer] : null

  return (
    <div style={{ minHeight: '100vh', background: 'transparent', display: 'flex', flexDirection: 'column' }}>

      {/* ── Top Nav ── */}
      <header
        style={{
          height: 64,
          padding: '0 20px',
          background: 'var(--color-paper)',
          borderBottom: '1px solid var(--color-ink-200)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          position: 'sticky',
          top: 0,
          zIndex: 10,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Link href="/" style={{ display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none', color: 'inherit' }}>
            <svg width="26" height="26" viewBox="0 0 32 32" fill="none" aria-hidden="true">
              <mask id="axon-mark-home">
                <rect width="32" height="32" fill="white" />
                <rect x="2" y="14.5" width="28" height="3" rx="1.5" fill="black" />
                <rect x="14.5" y="2" width="3" height="28" rx="1.5" fill="black" />
              </mask>
              <polygon points="16,5 27,16 16,27 5,16" fill="var(--color-accent)" mask="url(#axon-mark-home)" />
              <circle cx="16" cy="16" r="1.5" fill="var(--color-ink-900)" />
            </svg>
            <span style={{ fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 600, letterSpacing: '-0.01em', color: 'var(--color-ink-900)' }}>
              Axon
            </span>
          </Link>
          <span style={{ color: 'var(--color-ink-300)', fontSize: 14 }}>·</span>
          <span className="t-eyebrow">Home</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          {wide ? (
            <>
              <NavLinks variant="desktop" current="/home" />
              <TaskBell />
              <Link href="/settings" title="Settings" className="dash-icon-btn">
                <Settings size={13} strokeWidth={1.5} />
              </Link>
              <button onClick={handleSignOut} title="Sign out" className="dash-icon-btn">
                <LogOut size={13} strokeWidth={1.5} />
              </button>
            </>
          ) : (
            <>
              <TaskBell />
              <button
                onClick={() => setMenuOpen(o => !o)}
                className="dash-icon-btn"
                title="Menu"
                aria-label={menuOpen ? 'Close menu' : 'Open menu'}
                aria-expanded={menuOpen}
              >
                {menuOpen ? <X size={16} strokeWidth={1.5} /> : <Menu size={16} strokeWidth={1.5} />}
              </button>
            </>
          )}
        </div>
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
            <NavLinks variant="mobile" current="/home" onNavigate={() => setMenuOpen(false)} />
            <Link
              href="/settings"
              onClick={() => setMenuOpen(false)}
              style={{
                display: 'flex', alignItems: 'center', gap: 12,
                padding: '12px 14px', minHeight: 48,
                borderRadius: 'var(--radius-button)',
                textDecoration: 'none', color: 'var(--color-ink-800)',
                fontSize: 15, fontWeight: 500,
              }}
            >
              <Settings size={18} strokeWidth={1.5} color="var(--color-ink-500)" />
              Settings
            </Link>
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

      {/* ── Error Banner ── */}
      {error && (
        <div style={{ margin: '12px 20px 0', padding: '10px 14px', borderRadius: 'var(--radius-card)', background: 'var(--color-danger-bg)', border: '1px solid color-mix(in srgb, var(--color-danger) 25%, transparent)', color: 'var(--color-danger)', display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
          <AlertCircle size={14} strokeWidth={1.5} />
          {error}
        </div>
      )}

      {/* ── Page Body ── */}
      <div style={{ flex: 1, maxWidth: 1000, width: '100%', margin: '0 auto', padding: '20px 16px 56px' }}>

        {/* ── HERO: net profit (the 5-second "are we okay?") ── */}
        <section
          className="axon-rise"
          style={{
            ['--d' as string]: '0ms',
            display: 'grid',
            gridTemplateColumns: wide ? 'minmax(0,1.3fr) minmax(0,1fr)' : '1fr',
            borderRadius: 'var(--radius-card)', overflow: 'hidden',
            boxShadow: 'var(--shadow-pop)', marginBottom: 20,
            background: 'linear-gradient(135deg, var(--color-accent) 0%, var(--color-accent-700) 55%, #0a4d48 100%)',
            position: 'relative',
          }}
        >
          <div style={{ position: 'absolute', top: -40, right: -30, width: 200, height: 200, borderRadius: '50%', background: 'rgba(255,255,255,0.05)' }} />

          {/* Hot zone — the single most important number */}
          <div style={{ padding: '22px 26px', position: 'relative' }}>
            <p style={{ margin: '0 0 12px', fontSize: 13, color: 'rgba(255,255,255,0.65)' }}>
              {greeting}{data.user ? `, ${data.user.username}` : ''} · {dateStr}
            </p>
            <p className="t-eyebrow" style={{ color: 'rgba(255,255,255,0.6)', margin: '0 0 6px' }}>Net profit · {year} YTD</p>
            <p className="tabular" style={{ margin: 0, fontSize: wide ? 48 : 38, fontWeight: 700, color: '#fff', lineHeight: 1, letterSpacing: '-0.02em' }}>
              {loading || netYTD === null ? '—' : fmtFull(netAnim)}
            </p>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 14, flexWrap: 'wrap' }}>
              {monthNet !== null && (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '3px 9px', borderRadius: 'var(--radius-pill)', background: 'var(--color-moss-soft)', color: 'var(--color-moss)', fontSize: 11, fontWeight: 600, whiteSpace: 'nowrap' }}>
                  <ArrowUpRight size={13} strokeWidth={2} /> {fmtCurrency(monthNet)} net this month
                </span>
              )}
              {monthDelta !== null && monthDelta !== 0 && (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 2, fontSize: 12.5, fontWeight: 600, color: monthDelta > 0 ? '#bdeee8' : '#FFC9C2' }}>
                  {monthDelta > 0 ? <ArrowUpRight size={13} strokeWidth={2} /> : <ArrowDownRight size={13} strokeWidth={2} />}
                  {fmtCurrency(Math.abs(monthDelta))} vs last
                </span>
              )}
            </div>
          </div>

          {/* Net trend + cash triage, right of the hot zone */}
          <div style={{
            padding: '22px 26px', position: 'relative',
            borderLeft: wide ? '1px solid rgba(255,255,255,0.14)' : 'none',
            borderTop: wide ? 'none' : '1px solid rgba(255,255,255,0.14)',
            display: 'flex', flexDirection: 'column', justifyContent: 'space-between', gap: 16,
          }}>
            <div>
              <p className="t-eyebrow" style={{ color: 'rgba(255,255,255,0.6)', margin: '0 0 8px' }}>Net trend · {year}</p>
              {netSpark.length >= 2
                ? <Sparkline data={netSpark} w={220} h={42} color="#bdeee8" fill={false} strokeWidth={2} />
                : <p style={{ margin: 0, fontSize: 12, color: 'rgba(255,255,255,0.6)' }}>Not enough history yet</p>}
            </div>
            <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
              <HeroStat label="Collected" value={loading || collected === null ? '—' : fmtCurrency(collected)} />
              <HeroStat label="Expenses" value={loading || expensesYTD === null ? '—' : fmtCurrency(expensesYTD)} />
            </div>
          </div>
        </section>

        {/* ── KPI tiles (money-first, each opens a drill-down) ── */}
        <div
          className="axon-rise"
          style={{
            ['--d' as string]: '70ms',
            display: 'grid',
            gridTemplateColumns: wide ? 'repeat(4, 1fr)' : 'repeat(2, 1fr)',
            gap: 12, marginBottom: 22,
          }}
        >
          <KpiTile
            icon={<TrendingUp size={15} strokeWidth={1.5} color="var(--color-accent-300)" />}
            label="Revenue · MTD"
            value={loading || revThis === null ? '—' : fmtCurrency(revThis)}
            context={revDelta !== null
              ? <>{revDelta >= 0 ? '▲' : '▼'} {fmtCurrency(Math.abs(revDelta))} vs last</>
              : `${MONTH_ABBR[curMonth - 1]} so far`}
            contextTone={revDelta !== null ? (revDelta >= 0 ? 'moss' : 'danger') : 'muted'}
            spark={revenueSpark}
            sparkColor="var(--color-accent-300)"
            onOpen={() => setDrawer('rev')}
          />
          <KpiTile
            icon={<FileText size={15} strokeWidth={1.5} color="var(--color-gold)" />}
            label="Outstanding (AR)"
            value={loading || outstanding === null ? '—' : fmtCurrency(outstanding)}
            context={overdueAR > 0
              ? `${fmtCurrency(overdueAR)} overdue`
              : `${data.arSummary?.invoice_count ?? 0} open invoices`}
            contextTone={overdueAR > 0 ? 'danger' : 'muted'}
            onOpen={() => setDrawer('ar')}
          />
          <KpiTile
            icon={<Percent size={15} strokeWidth={1.5} color="var(--color-moss)" />}
            label="Win Rate"
            value={loading || !data.analytics ? '—' : `${data.analytics.win_rate}%`}
            context={data.analytics?.avg_cycle_time != null ? `${data.analytics.avg_cycle_time}d avg cycle` : '30-day period'}
            contextTone="moss"
            onOpen={() => setDrawer('win')}
          />
          <KpiTile
            icon={<Target size={15} strokeWidth={1.5} color="var(--color-accent-300)" />}
            label="Forecast"
            value={loading || !data.forecast ? '—' : fmtCurrency(data.forecast.weighted_total)}
            context={pipelineValue !== null ? `${fmtCurrency(pipelineValue)} pipeline` : 'weighted pipeline'}
            contextTone="muted"
            onOpen={() => setDrawer('forecast')}
          />
        </div>

        {/* ── Getting Started Checklist ── */}
        <GettingStartedChecklist />

        {/* ── Needs you today ── */}
        <TodayFocusSection
          taskCounts={data.taskCounts}
          arSummary={data.arSummary}
          loading={loading}
          onToast={showToast}
        />

        {/* ── Quick Actions ── */}
        <div style={{ marginBottom: 24 }}>
          <p className="t-eyebrow" style={{ margin: '0 0 10px' }}>Quick Actions</p>
          <div style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 4 }}>
            <Link
              href="/dashboard"
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 8,
                padding: '0 22px', minHeight: 44,
                borderRadius: 'var(--radius-pill)',
                background: 'var(--color-accent)',
                color: 'white',
                fontSize: 14, fontWeight: 600,
                textDecoration: 'none', whiteSpace: 'nowrap', flexShrink: 0,
                boxShadow: '0 1px 4px rgba(0,0,0,0.25)',
              }}
            >
              <Plus size={15} strokeWidth={2} />
              New Lead
            </Link>

            {([
              { label: 'View Pipeline',  icon: <Kanban size={14} strokeWidth={1.5} />,   href: '/pipeline' },
              { label: 'Create Invoice', icon: <FileText size={14} strokeWidth={1.5} />, href: '/bookkeeping', module: 'invoicing' as ModuleKey },
              { label: 'Log Expense',    icon: <Receipt size={14} strokeWidth={1.5} />,  href: '/expenses', module: 'bookkeeping' as ModuleKey },
            ] as { label: string; icon: ReactNode; href: string; module?: ModuleKey }[])
              .filter(({ module }) => !module || hasModule(module))
              .map(({ label, icon, href }) => (
              <Link
                key={href}
                href={href}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 8,
                  padding: '0 16px', minHeight: 44,
                  borderRadius: 'var(--radius-pill)',
                  background: 'var(--color-surface)',
                  border: '1px solid var(--color-ink-300)',
                  color: 'var(--color-ink-800)',
                  fontSize: 13, fontWeight: 500,
                  textDecoration: 'none', whiteSpace: 'nowrap', flexShrink: 0,
                }}
              >
                {icon}
                {label}
              </Link>
            ))}
          </div>
        </div>

        {/* ── Charts Row: Cash in vs out + Pipeline distribution ── */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: wide ? '1.4fr 1fr' : '1fr',
          gap: 14,
          marginBottom: 24,
        }}>
          {/* Cash in vs out */}
          <div style={{ background: 'var(--color-surface)', borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)', padding: '16px 18px 14px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
              <span className="t-eyebrow">Cash in vs out · {year}</span>
              <Link href="/bookkeeping" style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--color-accent-300)', textDecoration: 'none' }}>Report →</Link>
            </div>
            {loading ? (
              <div style={{ height: 140, opacity: 0.4 }} />
            ) : cashflow.length === 0 ? (
              <p style={{ fontSize: 13, color: 'var(--color-ink-400)', margin: 0, padding: '40px 0', textAlign: 'center' }}>
                No revenue or expenses logged yet.
              </p>
            ) : (
              <>
                <CashflowBars data={cashflow} h={140} />
                <div style={{ display: 'flex', gap: 18, marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--color-ink-100)' }}>
                  <Legend color="var(--color-accent)" label="In" val={fmtCurrency(cashIn)} />
                  <Legend color="var(--color-ink-200)" label="Out" val={fmtCurrency(cashOut)} />
                  <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
                    <p className="t-eyebrow" style={{ margin: '0 0 2px' }}>Net · YTD</p>
                    <p className="tabular" style={{ margin: 0, fontSize: 15, fontWeight: 700, color: (cashIn - cashOut) >= 0 ? 'var(--color-moss)' : 'var(--color-danger)' }}>
                      {(cashIn - cashOut) >= 0 ? '+' : ''}{fmtCurrency(cashIn - cashOut)}
                    </p>
                  </div>
                </div>
              </>
            )}
          </div>

          <PipelineRingChart />
        </div>

        {/* ── AI Insights Panel (analytical trends, capped) ── */}
        <AIInsightsPanel />

        {/* ── Top Scored Leads ── */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
            <p className="t-eyebrow" style={{ margin: 0 }}>Top Scored Leads</p>
            <Link href="/dashboard" style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, color: 'var(--color-accent-300)', textDecoration: 'none', fontWeight: 600 }}>
              View all <ArrowRight size={13} strokeWidth={1.5} />
            </Link>
          </div>

          {loading ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {[1, 2, 3].map(i => (
                <div key={i} style={{ height: 56, borderRadius: 'var(--radius-card)', background: 'var(--color-surface)', boxShadow: 'var(--shadow-card)', opacity: 0.5 }} />
              ))}
            </div>
          ) : data.recentLeads.length === 0 ? (
            <p style={{ fontSize: 14, color: 'var(--color-ink-400)', margin: 0, padding: '20px 0' }}>
              No leads yet — run the pipeline to import leads.
            </p>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: wide ? 'repeat(auto-fill, minmax(320px, 1fr))' : '1fr', gap: 8 }}>
              {data.recentLeads.map(lead => (
                <LeadRow key={lead.id} lead={lead} />
              ))}
            </div>
          )}
        </div>

        {/* ── Recent Activity (demoted) ── */}
        <ActivityFeed />

      </div>

      {/* ── Drill-down drawer ── */}
      <DrillDrawer
        open={!!dc}
        onClose={() => setDrawer(null)}
        eyebrow={dc?.eyebrow}
        title={dc?.title}
        rows={dc?.rows}
        cta={dc?.cta}
        note={dc?.note}
      />

      <ToastStack toasts={toasts} onDismiss={dismissToast} />
      <QuickAddFAB />
    </div>
  )
}

function LeadRow({ lead }: { lead: Lead }) {
  const [hover, setHover] = useState(false)
  const name = lead.owner_name ?? lead.address ?? lead.contact_name ?? '—'
  const sub  = [lead.city, lead.state].filter(Boolean).join(', ')
  return (
    <Link
      href={`/dashboard?lead=${lead.id}`}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: 'flex', alignItems: 'center', gap: 12, padding: '11px 14px',
        borderRadius: 'var(--radius-card)', background: 'var(--color-surface)',
        boxShadow: 'var(--shadow-card)', minHeight: 56, textDecoration: 'none', color: 'inherit',
        border: '1px solid transparent',
        transform: hover ? 'translateY(-2px)' : 'none',
        borderColor: hover ? 'var(--color-ink-200)' : 'transparent',
        transition: 'transform 140ms cubic-bezier(0.4,1,0.75,0.9), border-color 140ms',
      }}
    >
      <ScoreBadge grade={lead.score_grade} score={lead.lead_score} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{ margin: 0, fontSize: 14, fontWeight: 500, color: 'var(--color-ink-900)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</p>
        {sub && <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--color-ink-400)' }}>{sub}</p>}
      </div>
      {lead.estimated_job_value != null && lead.estimated_job_value > 0 && (
        <span className="tabular" style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-moss)', marginRight: 8 }}>
          {fmtCurrency(lead.estimated_job_value)}
        </span>
      )}
      <StatusPill status={lead.status} style={{ flexShrink: 0 }} />
    </Link>
  )
}

function HeroStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="t-eyebrow" style={{ color: 'rgba(255,255,255,0.55)', margin: '0 0 4px' }}>{label}</p>
      <p className="tabular" style={{ margin: 0, fontSize: 20, fontWeight: 600, color: 'white', lineHeight: 1 }}>{value}</p>
    </div>
  )
}

function Legend({ color, label, val }: { color: string; label: string; val: string }) {
  return (
    <div>
      <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--color-ink-400)', marginBottom: 2 }}>
        <span style={{ width: 9, height: 9, borderRadius: 2, background: color }} /> {label}
      </span>
      <p className="tabular" style={{ margin: 0, fontSize: 14, fontWeight: 700, color: 'var(--color-ink-800)' }}>{val}</p>
    </div>
  )
}
