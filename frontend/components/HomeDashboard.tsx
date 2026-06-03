'use client'
import { useEffect, useState, useCallback } from 'react'
import {
  TrendingUp, Users, CheckSquare, DollarSign,
  Plus, FileText, Receipt, Kanban,
  AlertTriangle, Clock, AlertCircle,
  LogOut, Settings, BookOpen, ArrowRight,
} from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { getMe, getTaskCounts, getPipelineStats, getARSummary, getLeads, getPipelineForecast } from '@/lib/api'
import { clearToken } from '@/lib/auth'
import type { Lead, PipelineCounts, ARSummary, ForecastData, User } from '@/lib/types'
import { ScoreBadge } from './ScoreBadge'
import { TaskBell } from './TaskBell'
import { OnboardingWizard } from './OnboardingWizard'
import { GettingStartedChecklist } from './GettingStartedChecklist'

const CLOSED_STAGES = new Set(['won', 'lost', 'not_interested'])

const STATUS_LABELS: Record<string, string> = {
  new: 'New',
  contacted: 'Contacted',
  qualified: 'Qualified',
  quote_sent: 'Quote Sent',
  won: 'Won',
  lost: 'Lost',
  not_interested: 'Not Interested',
  converted: 'Converted',
}

const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  new:            { bg: '#EDECEA',         text: 'var(--color-ink-500)' },
  contacted:      { bg: '#DCE7ED',         text: '#1F4258' },
  qualified:      { bg: '#D6E4EB',         text: 'var(--color-accent)' },
  quote_sent:     { bg: '#F4E7CB',         text: '#7A5419' },
  won:            { bg: '#E6EEDE',         text: '#3D5C39' },
  lost:           { bg: '#F0D9D6',         text: '#7A2F26' },
  not_interested: { bg: '#EDECEA',         text: 'var(--color-ink-400)' },
  converted:      { bg: '#E6EEDE',         text: '#3D5C39' },
}

interface DashData {
  user: User | null
  taskCounts: PipelineCounts | null
  pipelineStats: Record<string, { count: number; total_value: number }> | null
  arSummary: ARSummary | null
  forecast: ForecastData | null
  recentLeads: Lead[]
}

function fmtCurrency(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000)     return `$${(n / 1_000).toFixed(0)}k`
  return `$${n.toFixed(0)}`
}

export function HomeDashboard() {
  const router = useRouter()
  const [data, setData] = useState<DashData>({
    user: null, taskCounts: null, pipelineStats: null, arSummary: null, forecast: null, recentLeads: [],
  })
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string | null>(null)
  const [wide, setWide]       = useState(false)
  const [showOnboarding, setShowOnboarding] = useState(false)

  useEffect(() => {
    const check = () => setWide(window.innerWidth >= 640)
    check()
    window.addEventListener('resize', check)
    return () => window.removeEventListener('resize', check)
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const year = new Date().getFullYear()
      const [userRes, countsRes, statsRes, arRes, forecastRes, leadsRes] = await Promise.allSettled([
        getMe(),
        getTaskCounts(),
        getPipelineStats(),
        getARSummary(year),
        getPipelineForecast(),
        getLeads({ sort: 'score', page: 1, page_size: 5 }),
      ])
      setData({
        user:          userRes.status     === 'fulfilled' ? userRes.value             : null,
        taskCounts:    countsRes.status   === 'fulfilled' ? countsRes.value           : null,
        pipelineStats: statsRes.status    === 'fulfilled' ? statsRes.value            : null,
        arSummary:     arRes.status       === 'fulfilled' ? arRes.value               : null,
        forecast:      forecastRes.status === 'fulfilled' ? forecastRes.value         : null,
        recentLeads:   leadsRes.status    === 'fulfilled' ? leadsRes.value.results    : [],
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
  const outstanding = data.arSummary?.total_outstanding ?? 0
  const showAttention = overdue > 0 || outstanding > 0

  if (showOnboarding) {
    return <OnboardingWizard onComplete={() => { setShowOnboarding(false); load() }} />
  }

  return (
    <div style={{ minHeight: '100vh', background: 'var(--color-paper)', display: 'flex', flexDirection: 'column' }}>

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
            <svg width="26" height="26" viewBox="0 0 40 40" fill="none">
              <path d="M4 32 C 12 32, 14 22, 22 22 C 30 22, 30 14, 38 6"
                stroke="var(--color-ink-900)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
              <circle cx="4" cy="32" r="3" fill="var(--color-ink-900)" />
              <circle cx="22" cy="22" r="4" fill="var(--color-paper)" stroke="var(--color-ink-900)" strokeWidth="2.5" />
              <circle cx="38" cy="6" r="6" fill="var(--color-accent)" />
            </svg>
            <span style={{ fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 600, letterSpacing: '-0.01em', color: 'var(--color-ink-900)' }}>
              Axon
            </span>
          </Link>
          <span style={{ color: 'var(--color-ink-300)', fontSize: 14 }}>·</span>
          <span className="t-eyebrow">Home</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <Link href="/dashboard" title="Leads" className="dash-icon-btn" style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '0 10px', textDecoration: 'none', color: 'inherit', fontSize: 13 }}>
            <Users size={13} strokeWidth={1.5} />
            {wide && <span>Leads</span>}
          </Link>
          <Link href="/pipeline" title="Pipeline" className="dash-icon-btn" style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '0 10px', textDecoration: 'none', color: 'inherit', fontSize: 13 }}>
            <Kanban size={13} strokeWidth={1.5} />
            {wide && <span>Pipeline</span>}
          </Link>
          <Link href="/tasks" title="Tasks" className="dash-icon-btn" style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '0 10px', textDecoration: 'none', color: 'inherit', fontSize: 13 }}>
            <CheckSquare size={13} strokeWidth={1.5} />
            {wide && <span>Tasks</span>}
          </Link>
          <Link href="/expenses" title="Expenses" className="dash-icon-btn" style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '0 10px', textDecoration: 'none', color: 'inherit', fontSize: 13 }}>
            <Receipt size={13} strokeWidth={1.5} />
            {wide && <span>Expenses</span>}
          </Link>
          <Link href="/bookkeeping" title="Bookkeeping" className="dash-icon-btn" style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '0 10px', textDecoration: 'none', color: 'inherit', fontSize: 13 }}>
            <BookOpen size={13} strokeWidth={1.5} />
            {wide && <span>Books</span>}
          </Link>
          <TaskBell />
          <Link href="/settings" title="Settings" className="dash-icon-btn">
            <Settings size={13} strokeWidth={1.5} />
          </Link>
          <button onClick={handleSignOut} title="Sign out" className="dash-icon-btn">
            <LogOut size={13} strokeWidth={1.5} />
          </button>
        </div>
      </header>

      {/* ── Error Banner ── */}
      {error && (
        <div style={{ margin: '12px 20px 0', padding: '10px 14px', borderRadius: 'var(--radius-card)', background: 'var(--color-danger-bg)', border: '1px solid color-mix(in srgb, var(--color-danger) 25%, transparent)', color: 'var(--color-danger)', display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
          <AlertCircle size={14} strokeWidth={1.5} />
          {error}
        </div>
      )}

      {/* ── Page Body ── */}
      <div style={{ flex: 1, maxWidth: 800, width: '100%', margin: '0 auto', padding: '24px 16px 40px' }}>

        {/* ── B. Hero Greeting Card ── */}
        <div style={{ borderRadius: 'var(--radius-card)', background: 'var(--color-accent)', padding: '28px 24px', marginBottom: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
            <div>
              <p style={{ margin: 0, fontFamily: 'var(--font-display)', fontSize: 24, fontWeight: 600, color: 'white', lineHeight: 1.2 }}>
                {greeting}{data.user ? `, ${data.user.username}` : ''}
              </p>
              <p style={{ margin: '4px 0 0', fontSize: 13, color: 'rgba(255,255,255,0.65)' }}>{dateStr}</p>
            </div>
            <div style={{ textAlign: 'right' }}>
              <p className="t-eyebrow" style={{ color: 'rgba(255,255,255,0.55)', margin: '0 0 4px' }}>Pipeline Value</p>
              <p className="tabular" style={{ margin: 0, fontSize: 30, fontWeight: 700, color: 'white', lineHeight: 1 }}>
                {loading || pipelineValue === null ? '—' : fmtCurrency(pipelineValue)}
              </p>
            </div>
          </div>
        </div>

        {/* ── C. KPI Cards ── */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: wide ? 'repeat(4, 1fr)' : 'repeat(2, 1fr)',
          gap: 12,
          marginBottom: 20,
        }}>
          {/* Weighted Forecast */}
          <KPICard
            icon={<TrendingUp size={16} strokeWidth={1.5} color="var(--color-accent)" />}
            label="Forecast"
            value={loading || !data.forecast ? '—' : fmtCurrency(data.forecast.weighted_total)}
            sub="weighted pipeline"
          />
          {/* Active Leads */}
          <KPICard
            icon={<Users size={16} strokeWidth={1.5} color="var(--color-accent)" />}
            label="Active Leads"
            value={loading || activeLeads === null ? '—' : String(activeLeads)}
            sub="across all stages"
          />
          {/* Tasks Due */}
          <KPICard
            icon={<CheckSquare size={16} strokeWidth={1.5} color={overdue > 0 ? 'var(--color-danger)' : 'var(--color-accent)'} />}
            label="Due Today"
            value={loading || !data.taskCounts ? '—' : String(data.taskCounts.today)}
            sub={overdue > 0
              ? <span style={{ color: 'var(--color-danger)', fontWeight: 600 }}>{overdue} overdue</span>
              : 'on track'}
          />
          {/* Revenue YTD */}
          <KPICard
            icon={<DollarSign size={16} strokeWidth={1.5} color="#4F7A4A" />}
            label="Collected YTD"
            value={loading || !data.arSummary ? '—' : fmtCurrency(data.arSummary.total_collected)}
            sub={data.arSummary
              ? `${fmtCurrency(data.arSummary.total_outstanding)} outstanding`
              : '—'}
          />
        </div>

        {/* ── Getting Started Checklist ── */}
        <GettingStartedChecklist />

        {/* ── D. Quick Actions ── */}
        <div style={{ marginBottom: 24 }}>
          <p className="t-eyebrow" style={{ margin: '0 0 10px' }}>Quick Actions</p>
          <div style={{ display: 'flex', gap: 10, overflowX: 'auto', paddingBottom: 4 }}>
            {[
              { label: 'New Lead',       icon: <Plus size={15} strokeWidth={1.5} />,     href: '/dashboard' },
              { label: 'Create Invoice', icon: <FileText size={15} strokeWidth={1.5} />, href: '/bookkeeping' },
              { label: 'Log Expense',    icon: <Receipt size={15} strokeWidth={1.5} />,  href: '/expenses' },
              { label: 'View Pipeline',  icon: <Kanban size={15} strokeWidth={1.5} />,   href: '/pipeline' },
            ].map(({ label, icon, href }) => (
              <Link
                key={href}
                href={href}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '0 20px',
                  minHeight: 44,
                  borderRadius: 'var(--radius-pill)',
                  background: 'var(--color-accent)',
                  color: 'white',
                  fontSize: 14,
                  fontWeight: 500,
                  textDecoration: 'none',
                  whiteSpace: 'nowrap',
                  flexShrink: 0,
                }}
              >
                {icon}
                {label}
              </Link>
            ))}
          </div>
        </div>

        {/* ── E. Needs Attention ── */}
        {showAttention && (
          <div style={{ marginBottom: 24 }}>
            <p className="t-eyebrow" style={{ margin: '0 0 10px' }}>Needs Attention</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {overdue > 0 && (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px', borderRadius: 'var(--radius-card)', background: '#FDF2F1', borderLeft: '4px solid var(--color-danger)', minHeight: 44 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <AlertTriangle size={16} strokeWidth={1.5} color="var(--color-danger)" />
                    <span style={{ fontSize: 14, color: 'var(--color-ink-900)', fontWeight: 500 }}>
                      {overdue} task{overdue !== 1 ? 's' : ''} overdue
                    </span>
                  </div>
                  <Link href="/tasks" style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, color: 'var(--color-danger)', fontWeight: 500, textDecoration: 'none' }}>
                    Review <ArrowRight size={13} strokeWidth={1.5} />
                  </Link>
                </div>
              )}
              {outstanding > 0 && (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px', borderRadius: 'var(--radius-card)', background: '#FDF8EE', borderLeft: '4px solid var(--color-gold)', minHeight: 44 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <Clock size={16} strokeWidth={1.5} color="var(--color-gold)" />
                    <span style={{ fontSize: 14, color: 'var(--color-ink-900)', fontWeight: 500 }}>
                      {fmtCurrency(outstanding)} in unpaid invoices
                    </span>
                  </div>
                  <Link href="/bookkeeping" style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, color: 'var(--color-gold)', fontWeight: 500, textDecoration: 'none' }}>
                    View <ArrowRight size={13} strokeWidth={1.5} />
                  </Link>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── F. Recent Leads ── */}
        <div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
            <p className="t-eyebrow" style={{ margin: 0 }}>Recent Leads</p>
            <Link href="/dashboard" style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, color: 'var(--color-accent)', textDecoration: 'none', fontWeight: 500 }}>
              View all <ArrowRight size={13} strokeWidth={1.5} />
            </Link>
          </div>

          {loading ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {[1,2,3].map(i => (
                <div key={i} style={{ height: 56, borderRadius: 'var(--radius-card)', background: 'white', boxShadow: 'var(--shadow-card)', opacity: 0.5 }} />
              ))}
            </div>
          ) : data.recentLeads.length === 0 ? (
            <p style={{ fontSize: 14, color: 'var(--color-ink-400)', margin: 0, padding: '20px 0' }}>
              No leads yet — run the pipeline to import leads.
            </p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {data.recentLeads.map(lead => {
                const sc = STATUS_COLORS[lead.status] ?? { bg: '#EDECEA', text: 'var(--color-ink-500)' }
                const name = lead.owner_name ?? lead.address
                const sub  = [lead.city, lead.state].filter(Boolean).join(', ')
                return (
                  <Link
                    key={lead.id}
                    href="/dashboard"
                    style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 14px', borderRadius: 'var(--radius-card)', background: 'white', boxShadow: 'var(--shadow-card)', minHeight: 56, textDecoration: 'none', color: 'inherit' }}
                  >
                    <ScoreBadge grade={lead.score_grade} score={lead.lead_score} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <p style={{ margin: 0, fontSize: 14, fontWeight: 500, color: 'var(--color-ink-900)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</p>
                      {sub && <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--color-ink-400)' }}>{sub}</p>}
                    </div>
                    <span style={{ padding: '3px 10px', borderRadius: 'var(--radius-pill)', background: sc.bg, color: sc.text, fontSize: 12, fontWeight: 500, whiteSpace: 'nowrap', flexShrink: 0 }}>
                      {STATUS_LABELS[lead.status] ?? lead.status}
                    </span>
                  </Link>
                )
              })}
            </div>
          )}
        </div>

      </div>
    </div>
  )
}

function KPICard({ icon, label, value, sub }: {
  icon: React.ReactNode
  label: string
  value: string
  sub: React.ReactNode
}) {
  return (
    <div style={{ background: 'white', borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)', padding: '16px', minHeight: 88 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
        {icon}
        <span className="t-eyebrow">{label}</span>
      </div>
      <p className="tabular" style={{ margin: '0 0 4px', fontSize: 26, fontWeight: 700, color: 'var(--color-ink-900)', lineHeight: 1 }}>{value}</p>
      <p style={{ margin: 0, fontSize: 12, color: 'var(--color-ink-400)' }}>{sub}</p>
    </div>
  )
}
