'use client'
import { useEffect, useRef, useState } from 'react'
import {
  TrendingUp, Users, DollarSign, Percent, Plus, Kanban, Map as MapIcon,
  AlertTriangle, ArrowRight, Sparkles, Activity, Target, Clock,
  UserPlus, FileText, CheckSquare,
} from 'lucide-react'
import type { Lead } from '@/lib/types'
import { ScoreBadge } from '@/components/ScoreBadge'
import { useCountUp, MONTH_ABBR } from '@/components/home/dashboardKit'
import { statusTokens } from '@/lib/gradeColors'
import { coolingDays } from '@/lib/cooling'
import {
  DEMO_PNL, DEMO_STAGES, DEMO_OVERDUE_INVOICES, OPEN_STAGES,
  computeForecast, stageStats, winStats, type DemoActivityItem, type DemoActivityKind,
} from '@/lib/demoData'

export type DemoTab = 'dashboard' | 'leads' | 'pipeline' | 'map'

interface Props {
  leads: Lead[]
  activity: DemoActivityItem[]
  wide: boolean
  onOpen: (id: number) => void
  goTab: (tab: Exclude<DemoTab, 'dashboard'>) => void
  onNewLead: () => void
}

function fmtCurrency(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}k`
  return `$${n.toFixed(0)}`
}

function fmtCurrencyK(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}k`
  return `$${n.toFixed(0)}`
}

/** Count up on first mount only; later value changes render directly, so the
 *  live KPIs don't flash back to zero every time the visitor moves a card. */
export function useCountUpOnce(value: number): number {
  const animated = useCountUp(value, 600)
  const [settled, setSettled] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    timer.current = setTimeout(() => setSettled(true), 650)
    return () => { if (timer.current) clearTimeout(timer.current) }
  }, [])
  return settled ? value : animated
}

function AnimatedNumber({ value, format }: { value: number; format: (n: number) => string }) {
  const n = useCountUpOnce(value)
  return <>{format(n)}</>
}

/** Precompute the donut segments (arc length + running offset) so the JSX maps
 *  a plain list instead of mutating an accumulator mid-render. */
function ringSegments(
  stats: Record<string, { count: number }>,
  total: number,
  circumference: number,
) {
  let offset = 0
  return DEMO_STAGES.map(seg => {
    const count = stats[seg.key]?.count ?? 0
    const dashLen = total > 0 ? (count / total) * circumference : 0
    const s = { ...seg, count, dashLen, gap: circumference - dashLen, offset }
    offset += dashLen
    return s
  })
}

const ACTIVITY_META: Record<DemoActivityKind, { icon: React.ReactNode; color: string }> = {
  lead:    { icon: <UserPlus size={13} strokeWidth={1.8} />,   color: 'var(--color-accent)' },
  move:    { icon: <TrendingUp size={13} strokeWidth={1.8} />, color: 'var(--color-accent)' },
  invoice: { icon: <FileText size={13} strokeWidth={1.8} />,   color: 'var(--color-ink-500)' },
  task:    { icon: <CheckSquare size={13} strokeWidth={1.8} />, color: 'var(--color-moss)' },
  payment: { icon: <DollarSign size={13} strokeWidth={1.8} />, color: 'var(--color-moss)' },
}

/**
 * The demo dashboard. Every number here is derived from the live demo lead
 * state, so a card dragged on the Pipeline tab moves the forecast, the ring,
 * the win rate, and the top-leads list the visitor is looking at.
 */
export function DemoDashboard({ leads, activity, wide, onOpen, goTab, onNewLead }: Props) {
  const [hoveredMonth, setHoveredMonth] = useState<number | null>(null)
  const [hoveredStage, setHoveredStage] = useState<string | null>(null)

  const forecast = computeForecast(leads)
  const stats = stageStats(leads)
  const wins = winStats(leads)
  const openLeads = leads.filter(l => OPEN_STAGES.includes(l.status))

  const cooling = openLeads.filter(l => coolingDays(l.score_grade, l.status, l.stage_moved_at, l.created_at) != null)
  const coolingValue = cooling.reduce((s, l) => s + (l.estimated_job_value ?? 0), 0)
  const hot = leads.filter(l => l.status === 'qualified' || l.status === 'quote_sent')
  const hotValue = hot.reduce((s, l) => s + (l.estimated_job_value ?? 0), 0)

  const totalRevenue = DEMO_PNL.reduce((s, m) => s + m.revenue, 0)
  const totalNet = DEMO_PNL.reduce((s, m) => s + (m.revenue - m.expenses), 0)
  const maxBar = Math.max(...DEMO_PNL.flatMap(m => [m.revenue, m.expenses]))
  const thisMonth = new Date().getMonth()
  const monthLabel = (offset: number) => MONTH_ABBR[(thisMonth - offset + 12) % 12]

  const stageLabel = (key: string) => DEMO_STAGES.find(s => s.key === key)?.label ?? key
  const pipelineTotal = Object.values(stats).reduce((s, r) => s + r.count, 0)
  const topLeads = [...openLeads].sort((a, b) => (b.lead_score ?? 0) - (a.lead_score ?? 0)).slice(0, 5)

  const cx = 50, cy = 50, r = 36, strokeWidth = 10
  const circumference = 2 * Math.PI * r
  const ringSegs = ringSegments(stats, pipelineTotal, circumference)

  const insightLink: React.CSSProperties = {
    display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 500,
    whiteSpace: 'nowrap', flexShrink: 0, alignSelf: 'center',
    background: 'none', border: 'none', cursor: 'pointer', padding: 0,
    fontFamily: 'var(--font-sans)',
  }

  return (
    <div>
      {/* ── KPI Cards ── */}
      <div style={{ display: 'grid', gridTemplateColumns: wide ? 'repeat(5, 1fr)' : 'repeat(2, 1fr)', gap: 12, marginBottom: 20 }}>
        <KPICard icon={<TrendingUp size={16} strokeWidth={1.5} color="var(--color-accent)" />} label="Forecast"
          value={<AnimatedNumber value={forecast.weighted_total} format={fmtCurrency} />} sub="weighted pipeline" />
        <KPICard icon={<Users size={16} strokeWidth={1.5} color="var(--color-accent)" />} label="Active Leads"
          value={<AnimatedNumber value={openLeads.length} format={n => `${Math.round(n)}`} />} sub="across all stages" />
        <KPICard icon={<DollarSign size={16} strokeWidth={1.5} color="var(--color-moss)" />} label="Won"
          value={<AnimatedNumber value={wins.wonValue} format={fmtCurrency} />} sub={`${wins.won} job${wins.won === 1 ? '' : 's'} closed`} />
        <KPICard icon={<Percent size={16} strokeWidth={1.5} color="var(--color-moss)" />} label="Win Rate"
          value={<AnimatedNumber value={wins.ratePct ?? 0} format={n => `${Math.round(n)}%`} />} sub={`${wins.won}W–${wins.lost}L closed deals`} />
        <KPICard icon={<Clock size={16} strokeWidth={1.5} color="var(--color-gold)" />} label="Going Cold"
          value={<AnimatedNumber value={cooling.length} format={n => `${Math.round(n)}`} />} sub="A/B leads sitting idle" />
      </div>

      {/* ── Quick Actions (all real) ── */}
      <div style={{ marginBottom: 24 }}>
        <p className="t-eyebrow" style={{ margin: '0 0 10px' }}>Quick Actions</p>
        <div style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 4 }}>
          <button onClick={onNewLead} style={{
            display: 'inline-flex', alignItems: 'center', gap: 8,
            padding: '0 22px', minHeight: 44, borderRadius: 'var(--radius-pill)',
            background: 'var(--color-accent)', color: 'var(--text-on-accent)', border: 'none',
            fontSize: 14, fontWeight: 600, whiteSpace: 'nowrap',
            boxShadow: '0 1px 4px rgba(26,90,117,0.25)', cursor: 'pointer',
            fontFamily: 'var(--font-sans)',
          }}>
            <Plus size={15} strokeWidth={2} /> New Lead
          </button>
          {([
            ['View Pipeline', <Kanban key="k" size={14} strokeWidth={1.5} />, 'pipeline'],
            ['Browse Leads', <Users key="u" size={14} strokeWidth={1.5} />, 'leads'],
            ['Open the Map', <MapIcon key="m" size={14} strokeWidth={1.5} />, 'map'],
          ] as const).map(([label, icon, tab]) => (
            <button key={label} onClick={() => goTab(tab)} style={{
              display: 'inline-flex', alignItems: 'center', gap: 8,
              padding: '0 16px', minHeight: 44, borderRadius: 'var(--radius-pill)',
              background: 'var(--color-surface)', border: '1px solid var(--color-ink-300)',
              color: 'var(--color-ink-800)', fontSize: 13, fontWeight: 500,
              whiteSpace: 'nowrap', cursor: 'pointer', fontFamily: 'var(--font-sans)',
            }}>
              {icon} {label}
            </button>
          ))}
        </div>
      </div>

      {/* ── AI Insights (live) ── */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
          <div style={{
            width: 24, height: 24, borderRadius: 'var(--radius-button)',
            background: 'linear-gradient(135deg, var(--color-accent), var(--color-ocean-d))',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <Sparkles size={13} strokeWidth={1.8} color="white" />
          </div>
          <span className="t-eyebrow" style={{ letterSpacing: '0.1em' }}>AI Insights</span>
          <span style={{ fontSize: 10, color: 'var(--color-ink-400)' }}>Recomputed from this pipeline as you change it</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {[
            hot.length > 0 && {
              key: 'hot',
              title: `${hot.length} hot lead${hot.length === 1 ? '' : 's'} ready to close`,
              desc: `${fmtCurrency(hotValue)} sits in qualified and quote-sent. Focus your energy here for fastest revenue.`,
              type: 'positive' as const, icon: <Target size={15} strokeWidth={1.8} />,
              link: 'View pipeline', go: () => goTab('pipeline'),
            },
            cooling.length > 0 && {
              key: 'cooling',
              title: `${cooling.length} lead${cooling.length === 1 ? '' : 's'} going cold`,
              desc: `A/B-grade leads with no stage move in 5+ days — worth ${fmtCurrency(coolingValue)} in potential revenue. Schedule follow-ups.`,
              type: 'action' as const, icon: <Users size={15} strokeWidth={1.8} />,
              link: 'View leads', go: () => goTab('leads'),
            },
            wins.ratePct != null && {
              key: 'winrate',
              title: `Win rate at ${wins.ratePct}%`,
              desc: `${wins.won} of your last ${wins.won + wins.lost} closed deals landed. Keep quotes moving — speed to quote is your biggest lever.`,
              type: 'positive' as const, icon: <TrendingUp size={15} strokeWidth={1.8} />,
            },
            {
              key: 'overdue',
              title: `$${DEMO_OVERDUE_INVOICES.total.toLocaleString()} in overdue invoices`,
              desc: `${DEMO_OVERDUE_INVOICES.count} invoices past due. Send reminders to improve cash flow.`,
              type: 'warning' as const, icon: <AlertTriangle size={15} strokeWidth={1.8} />,
            },
          ].filter(Boolean).map(item => {
            const insight = item as {
              key: string; title: string; desc: string
              type: 'action' | 'positive' | 'warning'
              icon: React.ReactNode; link?: string; go?: () => void
            }
            const styles = {
              action:   { bg: 'var(--color-accent-50)', border: 'var(--color-accent-300)', iconBg: 'var(--color-accent)' },
              positive: { bg: 'var(--color-success-bg)', border: 'var(--color-success)', iconBg: 'var(--color-moss)' },
              warning:  { bg: 'var(--color-warning-bg)', border: 'var(--color-warning)', iconBg: 'var(--color-gold)' },
            }[insight.type]
            return (
              <div key={insight.key} style={{
                display: 'flex', alignItems: 'flex-start', gap: 12, padding: '14px 16px',
                borderRadius: 'var(--radius-card)', background: styles.bg, border: `1px solid ${styles.border}`,
              }}>
                <div style={{
                  width: 30, height: 30, borderRadius: 'var(--radius-button)', background: styles.iconBg,
                  display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, marginTop: 1,
                }}>
                  <span style={{ color: 'white', display: 'flex' }}>{insight.icon}</span>
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ margin: '0 0 3px', fontSize: 14, fontWeight: 600, color: 'var(--color-ink-900)', lineHeight: 1.3 }}>{insight.title}</p>
                  <p style={{ margin: 0, fontSize: 12.5, color: 'var(--color-ink-600)', lineHeight: 1.45 }}>{insight.desc}</p>
                </div>
                {insight.link && insight.go && (
                  <button onClick={insight.go} style={{ ...insightLink, color: styles.iconBg }}>
                    {insight.link} <ArrowRight size={12} strokeWidth={1.8} />
                  </button>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* ── Charts Row ── */}
      <div style={{ display: 'grid', gridTemplateColumns: wide ? '1.4fr 1fr' : '1fr', gap: 14, marginBottom: 24 }}>
        {/* Revenue trend */}
        <div style={{ background: 'var(--color-surface)', borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)', padding: '16px 18px', position: 'relative' }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 8 }}>
            <div>
              <span className="t-eyebrow" style={{ marginBottom: 4, display: 'block' }}>Revenue Trend</span>
              <span style={{ fontSize: 22, fontWeight: 700, fontFamily: 'var(--font-display)', color: 'var(--color-ink-900)' }}>
                {fmtCurrency(totalRevenue)}
              </span>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 11, color: 'var(--color-ink-400)', marginBottom: 2 }}>Net Profit</div>
              <div style={{ fontSize: 15, fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--color-moss)' }}>
                +{fmtCurrencyK(totalNet)}
              </div>
            </div>
          </div>
          {/* preserveAspectRatio="none" stretches SVG text, so month labels
              live in the HTML row below instead. */}
          <svg viewBox="0 0 100 86" style={{ width: '100%', height: 150, display: 'block' }} preserveAspectRatio="none"
            onMouseLeave={() => setHoveredMonth(null)}>
            <defs>
              <linearGradient id="demoRevGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--color-moss)" stopOpacity="0.25" />
                <stop offset="100%" stopColor="var(--color-moss)" stopOpacity="0.02" />
              </linearGradient>
            </defs>
            {[0.25, 0.5, 0.75].map(pct => (
              <line key={pct} x1="6" y1={12 + 70 * (1 - pct)} x2="94" y2={12 + 70 * (1 - pct)} stroke="var(--color-ink-100)" strokeWidth="0.3" />
            ))}
            {(() => {
              const points = DEMO_PNL.map((m, i) => ({
                x: 6 + (i / (DEMO_PNL.length - 1)) * 88,
                y: 12 + 70 - (m.revenue / maxBar) * 70,
              }))
              const expPts = DEMO_PNL.map((m, i) => ({
                x: 6 + (i / (DEMO_PNL.length - 1)) * 88,
                y: 12 + 70 - (m.expenses / maxBar) * 70,
              }))
              const line = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ')
              const area = `${line} L${points[points.length - 1].x},82 L${points[0].x},82 Z`
              const expLine = expPts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ')
              return (
                <>
                  <path d={area} fill="url(#demoRevGrad)" />
                  <path d={line} fill="none" stroke="var(--color-moss)" strokeWidth="1.5" strokeLinecap="round" />
                  <path d={expLine} fill="none" stroke="var(--color-rose)" strokeWidth="1" strokeDasharray="2,2" />
                  {DEMO_PNL.map((_, i) => (
                    <rect key={`h-${i}`} x={points[i].x - 8} y={12} width={16} height={70} fill="transparent"
                      onMouseEnter={() => setHoveredMonth(i)} style={{ cursor: 'crosshair' }} />
                  ))}
                  {hoveredMonth !== null && (
                    <>
                      <line x1={points[hoveredMonth].x} y1={12} x2={points[hoveredMonth].x} y2={82} stroke="var(--color-ink-300)" strokeWidth="0.3" strokeDasharray="1,1" />
                      <circle cx={points[hoveredMonth].x} cy={points[hoveredMonth].y} r="2" fill="var(--color-moss)" stroke="white" strokeWidth="0.8" />
                      <circle cx={expPts[hoveredMonth].x} cy={expPts[hoveredMonth].y} r="1.5" fill="var(--color-rose)" stroke="white" strokeWidth="0.6" />
                    </>
                  )}
                </>
              )
            })()}
          </svg>
          <div style={{ display: 'flex', justifyContent: 'space-between', padding: '0 6%', marginTop: 4 }}>
            {DEMO_PNL.map(m => (
              <span key={m.monthOffset} style={{ fontSize: 10, color: 'var(--color-ink-400)' }}>
                {monthLabel(m.monthOffset)}
              </span>
            ))}
          </div>
          {hoveredMonth !== null && (
            <div style={{
              position: 'absolute', bottom: 8, left: '50%', transform: 'translateX(-50%)',
              background: 'var(--color-ink-900)', color: 'white', borderRadius: 'var(--radius-button)',
              padding: '5px 10px', fontSize: 11, whiteSpace: 'nowrap', display: 'flex', gap: 12,
              boxShadow: 'var(--shadow-pop)',
            }}>
              <span style={{ color: 'var(--color-moss)' }}>Rev: {fmtCurrencyK(DEMO_PNL[hoveredMonth].revenue)}</span>
              <span style={{ color: 'var(--color-rose)' }}>Exp: {fmtCurrencyK(DEMO_PNL[hoveredMonth].expenses)}</span>
              <span style={{ fontWeight: 600 }}>Net: {fmtCurrencyK(DEMO_PNL[hoveredMonth].revenue - DEMO_PNL[hoveredMonth].expenses)}</span>
            </div>
          )}
          <div style={{ display: 'flex', gap: 14, marginTop: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--color-ink-500)' }}>
              <div style={{ width: 14, height: 2, background: 'var(--color-moss)', borderRadius: 1 }} /> Revenue
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--color-ink-500)' }}>
              <div style={{ width: 14, height: 2, background: 'var(--color-rose)', borderRadius: 1 }} /> Expenses
            </div>
          </div>
        </div>

        {/* Pipeline ring (live) */}
        <div style={{ background: 'var(--color-surface)', borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)', padding: '16px 18px' }}>
          <span className="t-eyebrow" style={{ display: 'block', marginBottom: 12 }}>Pipeline Distribution</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
            <div style={{ position: 'relative', width: 120, height: 120, flexShrink: 0 }}>
              <svg viewBox="0 0 100 100" style={{ width: '100%', height: '100%', transform: 'rotate(-90deg)' }}>
                {ringSegs.map(seg => {
                  if (seg.count === 0) return null
                  const isHovered = hoveredStage === seg.key
                  return (
                    <circle key={seg.key} cx={cx} cy={cy} r={r} fill="none"
                      stroke={seg.color} strokeWidth={isHovered ? strokeWidth + 3 : strokeWidth}
                      strokeDasharray={`${seg.dashLen} ${seg.gap}`} strokeDashoffset={-seg.offset} strokeLinecap="butt"
                      onMouseEnter={() => setHoveredStage(seg.key)} onMouseLeave={() => setHoveredStage(null)}
                      style={{ cursor: 'pointer', transition: 'stroke-width 0.2s ease', opacity: hoveredStage && !isHovered ? 0.5 : 1 }}
                    />
                  )
                })}
              </svg>
              <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', pointerEvents: 'none' }}>
                <span style={{ fontSize: 22, fontWeight: 700, fontFamily: 'var(--font-display)', color: 'var(--color-ink-900)', lineHeight: 1 }}>{pipelineTotal}</span>
                <span style={{ fontSize: 10, color: 'var(--color-ink-400)', marginTop: 2 }}>leads</span>
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: 1, minWidth: 0 }}>
              {DEMO_STAGES.map(seg => {
                const count = stats[seg.key]?.count ?? 0
                const pct = pipelineTotal > 0 ? Math.round((count / pipelineTotal) * 100) : 0
                const isHovered = hoveredStage === seg.key
                return (
                  <div key={seg.key} style={{
                    display: 'flex', alignItems: 'center', gap: 8, padding: '3px 6px',
                    borderRadius: 'var(--radius-button)',
                    background: isHovered ? 'var(--color-paper)' : 'transparent',
                    cursor: 'pointer',
                  }}
                    onMouseEnter={() => setHoveredStage(seg.key)} onMouseLeave={() => setHoveredStage(null)}>
                    <div style={{ width: 8, height: 8, borderRadius: '50%', background: seg.color, flexShrink: 0 }} />
                    <span style={{ fontSize: 12, color: 'var(--color-ink-700)', flex: 1 }}>{seg.label}</span>
                    <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-ink-900)', fontFamily: 'var(--font-mono)' }}>{count}</span>
                    <span style={{ fontSize: 10, color: 'var(--color-ink-400)', minWidth: 28, textAlign: 'right' }}>{pct}%</span>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      </div>

      {/* ── Forecast Breakdown (live) ── */}
      <div style={{ marginBottom: 24 }}>
        <p className="t-eyebrow" style={{ margin: '0 0 12px' }}>Weighted Forecast Breakdown</p>
        <div style={{ background: 'var(--color-surface)', borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)', overflow: 'hidden' }}>
          <div style={{ display: 'flex', padding: '10px 14px', borderBottom: '1px solid var(--color-ink-100)', gap: 8 }}>
            {['Stage', 'Leads', 'Raw', 'Wt%', 'Weighted'].map((h, i) => (
              <span key={h} style={{ flex: i === 0 ? 2 : 1, fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--color-ink-400)', textAlign: i === 0 ? 'left' : 'right' }}>{h}</span>
            ))}
          </div>
          {forecast.by_stage.map(row => (
            <div key={row.stage} style={{ display: 'flex', padding: '8px 14px', borderBottom: '1px solid var(--color-ink-50)', alignItems: 'center', gap: 8 }}>
              <span style={{ flex: 2, fontSize: 13, fontWeight: 500, color: 'var(--color-ink-800)' }}>{stageLabel(row.stage)}</span>
              <span className="tabular" style={{ flex: 1, fontSize: 13, color: 'var(--color-ink-600)', textAlign: 'right' }}>{row.count}</span>
              <span className="tabular" style={{ flex: 1, fontSize: 13, color: 'var(--color-ink-600)', textAlign: 'right' }}>{fmtCurrency(row.raw_value)}</span>
              <span className="tabular" style={{ flex: 1, fontSize: 13, color: 'var(--color-ink-400)', textAlign: 'right' }}>{row.weight_pct}%</span>
              <span className="tabular" style={{ flex: 1, fontSize: 13, fontWeight: 600, color: 'var(--color-accent-300)', textAlign: 'right' }}>{fmtCurrency(row.weighted_value)}</span>
            </div>
          ))}
          <div style={{ display: 'flex', padding: '10px 14px', background: 'var(--color-paper)', gap: 8 }}>
            <span style={{ flex: 2, fontSize: 13, fontWeight: 700, color: 'var(--color-ink-900)' }}>Total</span>
            <span style={{ flex: 1 }} /><span style={{ flex: 1 }} /><span style={{ flex: 1 }} />
            <span className="tabular" style={{ flex: 1, fontSize: 14, fontWeight: 700, color: 'var(--color-accent-300)', textAlign: 'right' }}>{fmtCurrency(forecast.weighted_total)}</span>
          </div>
        </div>
      </div>

      {/* ── Activity Feed (live — your demo actions land here) ── */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <Activity size={14} strokeWidth={1.8} color="var(--color-ink-400)" />
          <span className="t-eyebrow">Recent Activity</span>
        </div>
        <div style={{ background: 'var(--color-surface)', borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)', overflow: 'hidden' }}>
          {activity.slice(0, 7).map((item, idx, arr) => {
            const meta = ACTIVITY_META[item.kind]
            return (
              <div key={`${item.title}-${idx}`} style={{
                display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px',
                borderBottom: idx < arr.length - 1 ? '1px solid var(--color-ink-100)' : 'none',
              }}>
                <div style={{
                  width: 28, height: 28, borderRadius: '50%',
                  background: `color-mix(in srgb, ${meta.color} 12%, transparent)`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, color: meta.color,
                }}>{meta.icon}</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ margin: 0, fontSize: 13, fontWeight: 500, color: 'var(--color-ink-900)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.title}</p>
                  <p style={{ margin: 0, fontSize: 11, color: 'var(--color-ink-400)' }}>{item.detail}</p>
                </div>
                <span style={{ fontSize: 10, color: 'var(--color-ink-400)', whiteSpace: 'nowrap', flexShrink: 0 }}>{item.time}</span>
              </div>
            )
          })}
        </div>
      </div>

      {/* ── Top Scored Leads (live, clickable) ── */}
      <div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          <p className="t-eyebrow" style={{ margin: 0 }}>Top Scored Leads</p>
          <button onClick={() => goTab('leads')} style={{
            display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, color: 'var(--color-accent-300)',
            fontWeight: 500, background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'var(--font-sans)',
          }}>
            View all <ArrowRight size={13} strokeWidth={1.5} />
          </button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {topLeads.map(lead => {
            const sc = statusTokens(lead.status)
            return (
              <button key={lead.id} onClick={() => onOpen(lead.id)} style={{
                display: 'flex', alignItems: 'center', gap: 12, padding: '12px 14px', width: '100%',
                borderRadius: 'var(--radius-card)', background: 'var(--color-surface)', boxShadow: 'var(--shadow-card)',
                minHeight: 56, border: 'none', cursor: 'pointer', textAlign: 'left', fontFamily: 'var(--font-sans)',
              }}>
                <ScoreBadge grade={lead.score_grade} score={lead.lead_score} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ margin: 0, fontSize: 14, fontWeight: 500, color: 'var(--color-ink-900)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{lead.address ?? lead.owner_name}</p>
                  <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--color-ink-400)' }}>{lead.owner_name} · {lead.city}, {lead.state}</p>
                </div>
                {lead.estimated_job_value != null && lead.estimated_job_value > 0 && (
                  <span className="tabular" style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-moss)', marginRight: 8 }}>
                    {fmtCurrency(lead.estimated_job_value)}
                  </span>
                )}
                <span style={{ padding: '3px 10px', borderRadius: 'var(--radius-pill)', background: sc.bg, color: sc.fg, fontSize: 12, fontWeight: 500, whiteSpace: 'nowrap', flexShrink: 0 }}>
                  {sc.label}
                </span>
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function KPICard({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: React.ReactNode; sub: string }) {
  return (
    <div style={{
      background: 'var(--color-surface)', borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)',
      padding: '16px', minHeight: 88, position: 'relative', overflow: 'hidden',
    }}>
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3, background: 'linear-gradient(90deg, var(--color-accent) 0%, var(--color-accent-300) 100%)', opacity: 0.6 }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
        {icon}
        <span className="t-eyebrow">{label}</span>
      </div>
      <p className="tabular" style={{ margin: '0 0 4px', fontSize: 26, fontWeight: 700, color: 'var(--color-ink-900)', lineHeight: 1 }}>{value}</p>
      <p style={{ margin: 0, fontSize: 12, color: 'var(--color-ink-400)' }}>{sub}</p>
    </div>
  )
}
