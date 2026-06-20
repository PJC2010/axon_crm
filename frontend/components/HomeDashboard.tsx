'use client'
import { useEffect, useState, useCallback } from 'react'
import {
  TrendingUp, Users, CheckSquare,
  Plus, FileText, Receipt, Kanban,
  AlertCircle, ArrowUpRight, ArrowDownRight,
  LogOut, Settings, BookOpen, ArrowRight,
  Percent, Menu, X, CalendarDays,
} from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { getMe, getTaskCounts, getPipelineStats, getARSummary, getLeads, getPipelineForecast, getPipelineAnalytics, getPnL, getExpenseSummary } from '@/lib/api'
import { clearToken } from '@/lib/auth'
import type { Lead, PipelineCounts, ARSummary, ForecastData, User, PipelineAnalytics, PnLReport, ExpenseSummary } from '@/lib/types'
import { ScoreBadge } from './ScoreBadge'
import { KpiCard, StatusPill } from './ds'
import { TaskBell } from './TaskBell'
import { OnboardingWizard } from './OnboardingWizard'
import { GettingStartedChecklist } from './GettingStartedChecklist'
import { ToastStack, useToast } from './Toast'
import { AIInsightsPanel } from './AIInsightsPanel'
import { RevenueSparkChart } from './RevenueSparkChart'
import { PipelineRingChart } from './PipelineRingChart'
import { ActivityFeed } from './ActivityFeed'
import { TodayFocusSection } from './TodayFocusSection'
import { QuickAddFAB } from './QuickAddFAB'

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

export function HomeDashboard() {
  const router = useRouter()
  const [data, setData] = useState<DashData>({
    user: null, taskCounts: null, pipelineStats: null, arSummary: null, forecast: null, analytics: null, pnl: null, expenses: null, recentLeads: [],
  })
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string | null>(null)
  const [wide, setWide]       = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [showOnboarding, setShowOnboarding] = useState(false)
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
    router.push('/login')
  }

  const now      = new Date()
  const hour     = now.getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
  const dateStr  = now.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })

  const pipelineValue = data.pipelineStats
    ? Object.values(data.pipelineStats).reduce((s, v) => s + v.total_value, 0)
    : null

  const activeLeads = data.pipelineStats
    ? Object.entries(data.pipelineStats)
        .filter(([k]) => !CLOSED_STAGES.has(k))
        .reduce((s, [, v]) => s + v.count, 0)
    : null

  const overdue     = data.taskCounts?.overdue ?? 0
  const year        = now.getFullYear()

  // ── Money-first derived values ──
  const netYTD      = data.pnl?.net_profit ?? null
  const collected   = data.arSummary?.total_collected ?? null
  const outstanding = data.arSummary?.total_outstanding ?? null
  const overdueAR   = data.arSummary?.total_overdue ?? 0
  const expensesYTD = data.pnl?.total_expenses ?? data.expenses?.total ?? null

  // This-month vs last-month net, computed client-side from the P&L months array.
  const curMonth    = now.getMonth() + 1
  const thisMonth   = data.pnl?.months.find(m => m.month === curMonth) ?? null
  const lastMonth   = data.pnl?.months.find(m => m.month === curMonth - 1) ?? null
  const monthNet    = thisMonth ? thisMonth.net : null
  const monthDelta  = thisMonth && lastMonth ? thisMonth.net - lastMonth.net : null

  if (showOnboarding) {
    return <OnboardingWizard onComplete={() => { setShowOnboarding(false); load() }} />
  }

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
              <Link href="/dashboard" title="Leads" className="dash-icon-btn" style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '0 10px', textDecoration: 'none', color: 'inherit', fontSize: 13 }}>
                <Users size={13} strokeWidth={1.5} />
                <span>Leads</span>
              </Link>
              <Link href="/pipeline" title="Pipeline" className="dash-icon-btn" style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '0 10px', textDecoration: 'none', color: 'inherit', fontSize: 13 }}>
                <Kanban size={13} strokeWidth={1.5} />
                <span>Pipeline</span>
              </Link>
              <Link href="/tasks" title="Tasks" className="dash-icon-btn" style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '0 10px', textDecoration: 'none', color: 'inherit', fontSize: 13 }}>
                <CheckSquare size={13} strokeWidth={1.5} />
                <span>Tasks</span>
              </Link>
              <Link href="/calendar" title="Calendar" className="dash-icon-btn" style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '0 10px', textDecoration: 'none', color: 'inherit', fontSize: 13 }}>
                <CalendarDays size={13} strokeWidth={1.5} />
                <span>Calendar</span>
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
            {[
              { label: 'Leads',       icon: <Users size={18} strokeWidth={1.5} color="var(--color-ink-500)" />,       href: '/dashboard' },
              { label: 'Pipeline',    icon: <Kanban size={18} strokeWidth={1.5} color="var(--color-ink-500)" />,      href: '/pipeline' },
              { label: 'Tasks',       icon: <CheckSquare size={18} strokeWidth={1.5} color="var(--color-ink-500)" />, href: '/tasks' },
              { label: 'Calendar',    icon: <CalendarDays size={18} strokeWidth={1.5} color="var(--color-ink-500)" />, href: '/calendar' },
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
      <div style={{ flex: 1, maxWidth: 960, width: '100%', margin: '0 auto', padding: '24px 16px 40px' }}>

        {/* ── Money Hero (hot zone: are we okay?) ── */}
        <div style={{
          borderRadius: 'var(--radius-card)',
          background: 'linear-gradient(135deg, var(--color-accent) 0%, var(--color-ocean-d) 100%)',
          padding: '24px 24px', marginBottom: 20,
          position: 'relative', overflow: 'hidden',
        }}>
          <div style={{
            position: 'absolute', top: -30, right: -20, width: 160, height: 160,
            borderRadius: '50%', background: 'rgba(255,255,255,0.06)',
          }} />
          <div style={{
            position: 'absolute', bottom: -40, right: 60, width: 100, height: 100,
            borderRadius: '50%', background: 'rgba(255,255,255,0.04)',
          }} />

          {/* Subordinate greeting */}
          <p style={{ margin: '0 0 14px', fontSize: 13, color: 'rgba(255,255,255,0.65)', position: 'relative' }}>
            {greeting}{data.user ? `, ${data.user.username}` : ''} · {dateStr}
          </p>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: 20, position: 'relative' }}>
            {/* The single most important number — top-left, large & bold */}
            <div>
              <p className="t-eyebrow" style={{ color: 'rgba(255,255,255,0.55)', margin: '0 0 4px' }}>Net Profit · {year} YTD</p>
              <p className="tabular" style={{ margin: 0, fontSize: 38, fontWeight: 700, color: 'white', lineHeight: 1 }}>
                {loading || netYTD === null ? '—' : fmtCurrency(netYTD)}
              </p>
              {monthNet !== null && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
                  <span style={{ fontSize: 13, color: 'rgba(255,255,255,0.75)' }}>
                    {fmtCurrency(monthNet)} this month
                  </span>
                  {monthDelta !== null && monthDelta !== 0 && (
                    <span style={{
                      display: 'inline-flex', alignItems: 'center', gap: 2,
                      fontSize: 12, fontWeight: 600,
                      color: monthDelta > 0 ? '#BFE3B5' : '#FFC9C2',
                    }}>
                      {monthDelta > 0
                        ? <ArrowUpRight size={13} strokeWidth={2} />
                        : <ArrowDownRight size={13} strokeWidth={2} />}
                      {fmtCurrency(Math.abs(monthDelta))} vs last
                    </span>
                  )}
                </div>
              )}
            </div>

            {/* Cash triage: money in · owed to me · money out */}
            <div style={{ display: 'flex', gap: 22, flexWrap: 'wrap' }}>
              <HeroStat label="Collected" value={loading || collected === null ? '—' : fmtCurrency(collected)} />
              <HeroStat
                label="Outstanding"
                value={loading || outstanding === null ? '—' : fmtCurrency(outstanding)}
                sub={overdueAR > 0 ? `${fmtCurrency(overdueAR)} overdue` : undefined}
                subDanger={overdueAR > 0}
              />
              <HeroStat label="Expenses" value={loading || expensesYTD === null ? '—' : fmtCurrency(expensesYTD)} />
            </div>
          </div>
        </div>

        {/* ── Secondary KPI strip (what needs me / how am I trending) ── */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: wide ? 'repeat(4, 1fr)' : 'repeat(2, 1fr)',
          gap: 12,
          marginBottom: 20,
        }}>
          <KPICard
            icon={<CheckSquare size={16} strokeWidth={1.5} color={overdue > 0 ? 'var(--color-danger)' : 'var(--color-accent)'} />}
            label="Due Today"
            value={loading || !data.taskCounts ? '—' : String(data.taskCounts.today)}
            sub={overdue > 0
              ? <span style={{ color: 'var(--color-danger)', fontWeight: 600 }}>{overdue} overdue</span>
              : 'on track'}
            href="/tasks"
          />
          <KPICard
            icon={<Users size={16} strokeWidth={1.5} color="var(--color-accent)" />}
            label="Active Leads"
            value={loading || activeLeads === null ? '—' : String(activeLeads)}
            sub="across all stages"
            href="/dashboard"
          />
          <KPICard
            icon={<Percent size={16} strokeWidth={1.5} color="var(--color-moss)" />}
            label="Win Rate"
            value={loading || !data.analytics ? '—' : `${data.analytics.win_rate}%`}
            sub={data.analytics?.avg_cycle_time != null
              ? `${data.analytics.avg_cycle_time}d avg cycle`
              : '30-day period'}
            href="/pipeline"
          />
          <KPICard
            icon={<TrendingUp size={16} strokeWidth={1.5} color="var(--color-accent)" />}
            label="Forecast"
            value={loading || !data.forecast ? '—' : fmtCurrency(data.forecast.weighted_total)}
            sub={pipelineValue !== null ? `${fmtCurrency(pipelineValue)} pipeline` : 'weighted pipeline'}
            href="/pipeline"
          />
        </div>

        {/* ── Getting Started Checklist ── */}
        <GettingStartedChecklist />

        {/* ── Today's Focus ── */}
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
                boxShadow: '0 1px 4px rgba(26,90,117,0.25)',
              }}
            >
              <Plus size={15} strokeWidth={2} />
              New Lead
            </Link>

            {[
              { label: 'View Pipeline',  icon: <Kanban size={14} strokeWidth={1.5} />,   href: '/pipeline' },
              { label: 'Create Invoice', icon: <FileText size={14} strokeWidth={1.5} />, href: '/bookkeeping' },
              { label: 'Log Expense',    icon: <Receipt size={14} strokeWidth={1.5} />,  href: '/expenses' },
            ].map(({ label, icon, href }) => (
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

        {/* ── Charts Row: Revenue Trend + Pipeline Distribution ── */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: wide ? '1.4fr 1fr' : '1fr',
          gap: 14,
          marginBottom: 24,
        }}>
          <RevenueSparkChart year={year} />
          <PipelineRingChart />
        </div>

        {/* ── AI Insights Panel (analytical trends, capped) ── */}
        <AIInsightsPanel />

        {/* ── Top Scored Leads ── */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
            <p className="t-eyebrow" style={{ margin: 0 }}>Top Scored Leads</p>
            <Link href="/dashboard" style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, color: 'var(--color-accent)', textDecoration: 'none', fontWeight: 500 }}>
              View all <ArrowRight size={13} strokeWidth={1.5} />
            </Link>
          </div>

          {loading ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {[1,2,3].map(i => (
                <div key={i} style={{ height: 56, borderRadius: 'var(--radius-card)', background: 'var(--color-surface)', boxShadow: 'var(--shadow-card)', opacity: 0.5 }} />
              ))}
            </div>
          ) : data.recentLeads.length === 0 ? (
            <p style={{ fontSize: 14, color: 'var(--color-ink-400)', margin: 0, padding: '20px 0' }}>
              No leads yet — run the pipeline to import leads.
            </p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {data.recentLeads.map(lead => {
                const name = lead.owner_name ?? lead.address ?? lead.contact_name ?? '—'
                const sub  = [lead.city, lead.state].filter(Boolean).join(', ')
                return (
                  <Link
                    key={lead.id}
                    href="/dashboard"
                    style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 14px', borderRadius: 'var(--radius-card)', background: 'var(--color-surface)', boxShadow: 'var(--shadow-card)', minHeight: 56, textDecoration: 'none', color: 'inherit' }}
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
              })}
            </div>
          )}
        </div>

        {/* ── Recent Activity (demoted) ── */}
        <ActivityFeed />

      </div>

      <ToastStack toasts={toasts} onDismiss={dismissToast} />
      <QuickAddFAB />
    </div>
  )
}

function KPICard({ icon, label, value, sub, href }: {
  icon: React.ReactNode
  label: string
  value: string
  sub: React.ReactNode
  href?: string
}) {
  const card = <KpiCard icon={icon} label={label} value={value} sub={sub} />
  return href
    ? <Link href={href} style={{ display: 'block', textDecoration: 'none', color: 'inherit' }}>{card}</Link>
    : card
}

function HeroStat({ label, value, sub, subDanger }: {
  label: string
  value: string
  sub?: string
  subDanger?: boolean
}) {
  return (
    <div>
      <p className="t-eyebrow" style={{ color: 'rgba(255,255,255,0.55)', margin: '0 0 4px' }}>{label}</p>
      <p className="tabular" style={{ margin: 0, fontSize: 20, fontWeight: 600, color: 'white', lineHeight: 1 }}>{value}</p>
      {sub && (
        <p style={{ margin: '3px 0 0', fontSize: 11, fontWeight: 600, color: subDanger ? '#FFC9C2' : 'rgba(255,255,255,0.6)' }}>{sub}</p>
      )}
    </div>
  )
}
