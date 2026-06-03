'use client'
import { useEffect, useState, useCallback } from 'react'
import { TrendingUp, Clock, Trophy, BarChart3 } from 'lucide-react'
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
  contacted: 'var(--color-ocean, #3B82F6)',
  qualified: 'var(--color-accent)',
  quote_sent: 'var(--color-gold, #F59E0B)',
  won: 'var(--color-moss)',
}

export function PipelineAnalytics() {
  const [data, setData] = useState<AnalyticsData | null>(null)
  const [days, setDays] = useState(90)
  const [loading, setLoading] = useState(true)

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

      {/* KPI cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12 }}>
        <KpiCard icon={<Trophy size={16} strokeWidth={1.5} />} label="Win Rate" value={`${data.win_rate}%`} color="var(--color-moss)" />
        <KpiCard icon={<Clock size={16} strokeWidth={1.5} />} label="Avg Cycle Time" value={data.avg_cycle_time != null ? `${data.avg_cycle_time}d` : '—'} color="var(--color-accent)" />
        <KpiCard icon={<TrendingUp size={16} strokeWidth={1.5} />} label="Leads Won" value={String(data.leads_won)} color="var(--color-gold, #F59E0B)" />
        <KpiCard icon={<BarChart3 size={16} strokeWidth={1.5} />} label="Period" value={`${data.period_days} days`} color="var(--color-ink-400)" />
      </div>

      {/* Conversion funnel */}
      <section>
        <h3 className="t-eyebrow" style={{ marginBottom: 14 }}>Conversion funnel</h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {FUNNEL_STAGES.map(stage => {
            const count = data.funnel[stage] ?? 0
            const pct = maxFunnel > 0 ? (count / maxFunnel) * 100 : 0
            return (
              <div key={stage} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ width: 80, fontSize: 12, fontWeight: 500, color: 'var(--color-ink-700)', textAlign: 'right' }}>
                  {STAGE_LABELS[stage] ?? stage}
                </span>
                <div style={{ flex: 1, height: 28, background: 'var(--color-ink-100)', borderRadius: 'var(--radius-card)', overflow: 'hidden', position: 'relative' }}>
                  <div
                    style={{
                      height: '100%',
                      width: `${Math.max(pct, 2)}%`,
                      background: STAGE_COLORS[stage] ?? 'var(--color-ink-300)',
                      borderRadius: 'var(--radius-card)',
                      transition: 'width 0.4s ease',
                      display: 'flex',
                      alignItems: 'center',
                      paddingLeft: 8,
                    }}
                  >
                    {pct > 15 && (
                      <span style={{ fontSize: 11, fontWeight: 600, color: '#fff' }}>{count}</span>
                    )}
                  </div>
                  {pct <= 15 && (
                    <span style={{ position: 'absolute', left: `calc(${Math.max(pct, 2)}% + 8px)`, top: '50%', transform: 'translateY(-50%)', fontSize: 11, fontWeight: 600, color: 'var(--color-ink-500)' }}>
                      {count}
                    </span>
                  )}
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
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--color-ink-200)' }}>
                {['Stage', 'Avg Days'].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--color-ink-400)', fontWeight: 500, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Object.entries(data.avg_days_per_stage).map(([stage, avgDays]) => (
                <tr key={stage} style={{ borderBottom: '1px solid var(--color-ink-100)' }}>
                  <td style={{ padding: '8px', fontWeight: 500 }}>{STAGE_LABELS[stage] ?? stage}</td>
                  <td style={{ padding: '8px', color: 'var(--color-ink-700)' }}>
                    {avgDays != null ? (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span>{avgDays}d</span>
                        <div style={{ flex: 1, maxWidth: 120, height: 6, background: 'var(--color-ink-100)', borderRadius: 3 }}>
                          <div style={{ height: '100%', width: `${Math.min((avgDays / 30) * 100, 100)}%`, background: avgDays > 14 ? 'var(--color-danger)' : avgDays > 7 ? 'var(--color-gold, #F59E0B)' : 'var(--color-moss)', borderRadius: 3 }} />
                        </div>
                      </div>
                    ) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  )
}

function KpiCard({ icon, label, value, color }: { icon: React.ReactNode; label: string; value: string; color: string }) {
  return (
    <div style={{
      padding: '16px 18px',
      background: 'var(--color-paper)',
      border: '1px solid var(--color-ink-200)',
      borderRadius: 'var(--radius-card)',
      boxShadow: 'var(--shadow-card)',
    }}>
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
