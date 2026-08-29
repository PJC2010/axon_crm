'use client'
import { useEffect, useState, useCallback } from 'react'
import { Sparkles, TrendingUp, AlertTriangle, Clock, ArrowRight } from 'lucide-react'
import Link from 'next/link'
import { getPipelineAnalytics } from '@/lib/api'

interface Insight {
  id: string
  icon: React.ReactNode
  title: string
  description: string
  type: 'action' | 'positive' | 'warning'
  link?: string
  linkLabel?: string
}

const TYPE_STYLES: Record<string, { bg: string; border: string; iconBg: string }> = {
  action:   { bg: 'var(--color-accent-50)',  border: 'var(--color-accent-300)', iconBg: 'var(--color-accent)' },
  positive: { bg: 'var(--color-success-bg)',                 border: 'var(--color-success)',                 iconBg: 'var(--color-moss)' },
  warning:  { bg: 'var(--color-warning-bg)',                 border: 'var(--color-warning)',                 iconBg: 'var(--color-gold)' },
}

// Analytical/trend insights only. Action items (overdue tasks/invoices, stale &
// hot leads, stuck deals) live in the unified "Needs Attention" action center,
// so they are intentionally not duplicated here.
const MAX_INSIGHTS = 3

export function AIInsightsPanel() {
  const [insights, setInsights] = useState<Insight[]>([])
  const [loading, setLoading] = useState(true)

  const generate = useCallback(async () => {
    setLoading(true)
    try {
      const [analytics30, analytics90] = await Promise.allSettled([
        getPipelineAnalytics(30),
        getPipelineAnalytics(90),
      ])

      const items: Insight[] = []

      if (analytics30.status === 'fulfilled' && analytics90.status === 'fulfilled') {
        const a30 = analytics30.value
        const a90 = analytics90.value
        // An insight is a claim about the business. If either win rate was not
        // measured — the panel degraded rather than 500ing (api/deps.py::
        // soft_query) — there is no comparison to draw, and treating null as 0
        // would manufacture a "win rate dipped" warning out of a slow database.
        const w30 = a30.win_rate
        const w90 = a90.win_rate
        if (w30 != null && w90 != null && w30 > w90) {
          items.push({
            id: 'win-rate-up',
            icon: <TrendingUp size={15} strokeWidth={1.8} />,
            title: `Win rate trending up`,
            description: `Your 30-day win rate is ${w30}% vs ${w90}% over 90 days — your close process is improving.`,
            type: 'positive',
          })
        } else if (w30 != null && w90 != null && w30 < w90 && w90 > 0) {
          items.push({
            id: 'win-rate-down',
            icon: <AlertTriangle size={15} strokeWidth={1.8} />,
            title: `Win rate dipped recently`,
            description: `30-day win rate (${w30}%) is below your 90-day average (${w90}%). Review recent lost deals for patterns.`,
            type: 'warning',
            link: '/pipeline',
            linkLabel: 'Review pipeline',
          })
        }

        if (a30.avg_cycle_time != null && a30.avg_cycle_time > 14) {
          items.push({
            id: 'slow-cycle',
            icon: <Clock size={15} strokeWidth={1.8} />,
            title: 'Long sales cycle detected',
            description: `Deals are averaging ${a30.avg_cycle_time} days to close. Consider adding follow-up automation to speed up conversions.`,
            type: 'action',
            link: '/pipeline',
            linkLabel: 'View analytics',
          })
        }
      }

      setInsights(items.slice(0, MAX_INSIGHTS))
    } catch {
      /* silently fail */
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { generate() }, [generate])

  if (loading) {
    return (
      <div style={{ padding: '20px 0' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
          <Sparkles size={14} strokeWidth={1.8} color="var(--color-accent)" />
          <span className="t-eyebrow">AI Insights</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {[1,2].map(i => (
            <div key={i} style={{ height: 72, borderRadius: 'var(--radius-card)', background: 'var(--color-surface)', boxShadow: 'var(--shadow-card)', opacity: 0.5 }} />
          ))}
        </div>
      </div>
    )
  }

  if (insights.length === 0) return null

  return (
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
        <span style={{ fontSize: 10, color: 'var(--color-ink-400)', fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>
          Based on your pipeline data
        </span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {insights.map(insight => {
          const s = TYPE_STYLES[insight.type]
          return (
            <div
              key={insight.id}
              style={{
                borderRadius: 'var(--radius-card)',
                background: s.bg,
                border: `1px solid ${s.border}`,
                overflow: 'hidden',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, padding: '14px 16px' }}>
                <div style={{
                  width: 30, height: 30, borderRadius: 'var(--radius-button)',
                  background: s.iconBg,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  flexShrink: 0, marginTop: 1,
                }}>
                  <span style={{ color: 'white', display: 'flex' }}>{insight.icon}</span>
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ margin: '0 0 3px', fontSize: 14, fontWeight: 600, color: 'var(--color-ink-900)', lineHeight: 1.3 }}>
                    {insight.title}
                  </p>
                  <p style={{ margin: 0, fontSize: 12.5, color: 'var(--color-ink-600)', lineHeight: 1.45 }}>
                    {insight.description}
                  </p>
                </div>
                {insight.link && (
                  <Link
                    href={insight.link}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 4,
                      fontSize: 12, fontWeight: 500, color: s.iconBg,
                      textDecoration: 'none', whiteSpace: 'nowrap', flexShrink: 0,
                      alignSelf: 'center',
                    }}
                  >
                    {insight.linkLabel} <ArrowRight size={12} strokeWidth={1.8} />
                  </Link>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
