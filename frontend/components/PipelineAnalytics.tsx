'use client'
import { useEffect, useState, useCallback } from 'react'
import { TrendingUp, Clock, Trophy, BarChart3, ArrowDown, AlertTriangle } from 'lucide-react'
import { getPipelineAnalytics } from '@/lib/api'
import type { PipelineAnalytics as AnalyticsData } from '@/lib/types'

const FUNNEL_STAGES = ['new', 'contacted', 'qualified', 'quote_sent', 'won']

const STAGE_LABELS: Record<string, string> = {
  new: 'New',
  contacted: 'Contacted',
  qualified: 'Qualified',
  quote_sent: 'Quote Sent',
  won: 'Won',
  lost: 'Lost',
  not_interested: 'Not Interested',
}

const STAGE_COLORS: Record<string, string> = {
  new: 'var(--color-ink-300)',
  contacted: 'var(--color-ocean)',
  qualified: 'var(--color-accent)',
  quote_sent: 'var(--color-gold)',
  won: 'var(--color-moss)',
}

const STAGE_BG: Record<string, string> = {
  new: 'var(--color-ink-50)',
  contacted: 'var(--color-info-bg)',
  qualified: 'var(--color-accent-100)',
  quote_sent: 'var(--color-gold-soft)',
  won: 'var(--color-success-bg)',
}

export function PipelineAnalytics() {
  const [data, setData] = useState<AnalyticsData | null>(null)
  const [days, setDays] = useState(90)
  const [loading, setLoading] = useState(true)
  const [hoveredStage, setHoveredStage] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const d = await getPipelineAnalytics(days)
      setData(d)
    } catch {
      /* silently fail */
    } finally {
      setLoading(false)
    }
  }, [days])

  useEffect(() => { load() }, [load])

  if (loading && !data) {
    return <p style={{ fontSize: 13, color: 'var(--color-ink-400)', padding: 20 }}>Loading analytics…</p>
  }
  if (!data) {
    return <p style={{ fontSize: 13, color: 'var(--color-ink-400)', padding: 20 }}>Unable to load analytics.</p>
  }

  const maxFunnel = Math.max(...FUNNEL_STAGES.map(s => data.funnel[s] ?? 0), 1)

  return (
    <div style={{ padding: '20px 16px', display: 'flex', flexDirection: 'column', gap: 24 }}>
      {/* Period selector */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 12, color: 'var(--color-ink-400)', fontWeight: 500 }}>Period:</span>
        {[30, 60, 90, 180].map(d => (
          <button
            key={d}
            onClick={() => setDays(d)}
            style={{
              padding: '4px 12px',
              fontSize: 12,
              fontWeight: 500,
              borderRadius: 'var(--radius-pill)',
              border: days === d ? 'none' : '1px solid var(--color-ink-200)',
              background: days === d ? 'var(--color-ink-900)' : 'transparent',
              color: days === d ? 'var(--color-paper)' : 'var(--color-ink-500)',
              cursor: 'pointer',
            }}
          >
            {d}d
          </button>
        ))}
      </div>

      {/* Some figures could not be measured — say so, rather than letting the
          em dashes read as zeroes. `degraded` lists the panels whose query hit
          DASHBOARD_STATEMENT_TIMEOUT_MS. */}
      {data.degraded && data.degraded.length > 0 && (
        <div
          role="status"
          style={{
            display: 'flex', alignItems: 'center', gap: 8, padding: '10px 12px',
            borderRadius: 8, background: 'var(--color-surface-2)',
            border: '1px solid var(--color-border)', color: 'var(--color-ink-400)',
            fontSize: 13,
          }}
        >
          <AlertTriangle size={15} strokeWidth={1.6} aria-hidden />
          <span>
            Some figures took too long to calculate and are shown as “—”. They are
            not zero. Try narrowing the period, or reload in a moment.
          </span>
        </div>
      )}

      {/* KPI cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12 }}>
        <KpiCard icon={<Trophy size={16} strokeWidth={1.5} />} label="Win Rate" value={data.win_rate != null ? `${data.win_rate}%` : '—'} color="var(--color-moss)" accent />
        <KpiCard icon={<Clock size={16} strokeWidth={1.5} />} label="Avg Cycle Time" value={data.avg_cycle_time != null ? `${data.avg_cycle_time}d` : '—'} color="var(--color-accent)" />
        <KpiCard icon={<TrendingUp size={16} strokeWidth={1.5} />} label="Leads Won" value={data.leads_won != null ? String(data.leads_won) : '—'} color="var(--color-gold)" />
        <KpiCard icon={<BarChart3 size={16} strokeWidth={1.5} />} label="Period" value={`${data.period_days} days`} color="var(--color-ink-400)" />
      </div>

      {/* Conversion funnel — trapezoid style */}
      <section>
        <h3 className="t-eyebrow" style={{ marginBottom: 16 }}>Conversion funnel</h3>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 0 }}>
          {FUNNEL_STAGES.map((stage, idx) => {
            const count = data.funnel[stage] ?? 0
            const widthPct = maxFunnel > 0 ? Math.max((count / maxFunnel) * 100, 12) : 12
            const prevCount = idx > 0 ? (data.funnel[FUNNEL_STAGES[idx - 1]] ?? 0) : null
            const convRate = prevCount && prevCount > 0 ? Math.round((count / prevCount) * 100) : null
            const isHovered = hoveredStage === stage
            const color = STAGE_COLORS[stage] ?? 'var(--color-ink-300)'
            const bg = STAGE_BG[stage] ?? 'var(--color-ink-50)'

            return (
              <div key={stage} style={{ width: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                {idx > 0 && convRate !== null && (
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 4,
                    padding: '3px 0', color: convRate >= 50 ? 'var(--color-moss)' : convRate >= 25 ? 'var(--color-gold)' : 'var(--color-danger)',
                    fontSize: 11, fontWeight: 600,
                  }}>
                    <ArrowDown size={10} strokeWidth={2} />
                    {convRate}% conversion
                  </div>
                )}
                <div
                  onMouseEnter={() => setHoveredStage(stage)}
                  onMouseLeave={() => setHoveredStage(null)}
                  style={{
                    width: `${widthPct}%`,
                    minWidth: 100,
                    padding: '12px 16px',
                    background: isHovered ? `color-mix(in srgb, ${color} 24%, var(--color-surface-hi))` : bg,
                    borderLeft: `4px solid ${color}`,
                    borderRadius: 'var(--radius-card)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    cursor: 'default',
                    transition: 'width 0.4s ease, background 0.2s ease, transform 0.15s ease',
                    transform: isHovered ? 'scale(1.02)' : 'scale(1)',
                    boxShadow: isHovered ? 'var(--shadow-pop)' : 'var(--shadow-card)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-ink-800)' }}>
                      {STAGE_LABELS[stage] ?? stage}
                    </span>
                  </div>
                  <span style={{
                    fontSize: 18, fontWeight: 700, fontFamily: 'var(--font-display)',
                    color,
                  }}>
                    {count}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      </section>

      {/* Avg days per stage */}
      {Object.keys(data.avg_days_per_stage).length > 0 && (
        <section>
          <h3 className="t-eyebrow" style={{ marginBottom: 14 }}>Average days in stage</h3>
          <div style={{
            background: 'var(--color-surface)', borderRadius: 'var(--radius-card)',
            boxShadow: 'var(--shadow-card)', overflow: 'hidden',
          }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--color-ink-200)' }}>
                  {['Stage', 'Avg Days', ''].map(h => (
                    <th key={h} style={{ textAlign: 'left', padding: '10px 14px', color: 'var(--color-ink-400)', fontWeight: 500, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.avg_days_per_stage).map(([stage, avgDays]) => (
                  <tr key={stage} style={{ borderBottom: '1px solid var(--color-ink-100)' }}>
                    <td style={{ padding: '10px 14px', fontWeight: 500 }}>{STAGE_LABELS[stage] ?? stage}</td>
                    <td style={{ padding: '10px 14px', color: 'var(--color-ink-700)', fontFamily: 'var(--font-mono)' }}>
                      {avgDays != null ? `${avgDays}d` : '—'}
                    </td>
                    <td style={{ padding: '10px 14px', width: 140 }}>
                      {avgDays != null && (
                        <div style={{ width: '100%', height: 8, background: 'var(--color-ink-100)', borderRadius: 4, overflow: 'hidden' }}>
                          <div style={{
                            height: '100%',
                            width: '100%',
                            transform: `scaleX(${Math.min(avgDays / 30, 1)})`,
                            transformOrigin: 'left',
                            background: avgDays > 14
                              ? 'linear-gradient(90deg, var(--color-danger), color-mix(in srgb, var(--color-danger) 60%, var(--color-surface)))'
                              : avgDays > 7
                              ? 'linear-gradient(90deg, var(--color-gold), color-mix(in srgb, var(--color-gold) 60%, var(--color-surface)))'
                              : 'linear-gradient(90deg, var(--color-moss), color-mix(in srgb, var(--color-moss) 60%, var(--color-surface)))',
                            borderRadius: 4,
                            transition: 'transform 0.4s ease',
                          }} />
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}

function KpiCard({ icon, label, value, color, accent }: { icon: React.ReactNode; label: string; value: string; color: string; accent?: boolean }) {
  return (
    <div style={{
      padding: '16px 18px',
      background: accent ? `color-mix(in srgb, ${color} 8%, white)` : 'var(--color-paper)',
      border: `1px solid ${accent ? `color-mix(in srgb, ${color} 20%, transparent)` : 'var(--color-ink-200)'}`,
      borderRadius: 'var(--radius-card)',
      boxShadow: 'var(--shadow-card)',
      position: 'relative',
      overflow: 'hidden',
    }}>
      {accent && (
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0, height: 3,
          background: color,
        }} />
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8, color }}>
        {icon}
        <span className="t-eyebrow" style={{ margin: 0 }}>{label}</span>
      </div>
      <p style={{ fontSize: 24, fontWeight: 700, fontFamily: 'var(--font-display)', color: 'var(--color-ink-900)', margin: 0 }}>
        {value}
      </p>
    </div>
  )
}
