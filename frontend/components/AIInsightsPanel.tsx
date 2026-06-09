'use client'
import { useEffect, useState, useCallback } from 'react'
import { Sparkles, TrendingUp, AlertTriangle, Target, Users, Clock, ArrowRight, Zap } from 'lucide-react'
import Link from 'next/link'
import { getPipelineAnalytics, getPipelineStats, getARSummary, getTaskCounts, getLeads } from '@/lib/api'
import type { Lead } from '@/lib/types'

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
  positive: { bg: '#E6EEDE',                 border: '#B8D4A8',                 iconBg: 'var(--color-moss)' },
  warning:  { bg: '#FDF8EE',                 border: '#E8D5A8',                 iconBg: 'var(--color-gold)' },
}

export function AIInsightsPanel() {
  const [insights, setInsights] = useState<Insight[]>([])
  const [loading, setLoading] = useState(true)

  const generate = useCallback(async () => {
    setLoading(true)
    try {
      const year = new Date().getFullYear()
      const [analytics30, analytics90, stats, ar, counts, staleLeads] = await Promise.allSettled([
        getPipelineAnalytics(30),
        getPipelineAnalytics(90),
        getPipelineStats(),
        getARSummary(year),
        getTaskCounts(),
        getLeads({ status: 'contacted', sort: 'updated_at', page: 1, page_size: 50 }),
      ])

      const items: Insight[] = []

      if (analytics30.status === 'fulfilled' && analytics90.status === 'fulfilled') {
        const a30 = analytics30.value
        const a90 = analytics90.value
        if (a30.win_rate > a90.win_rate) {
          items.push({
            id: 'win-rate-up',
            icon: <TrendingUp size={15} strokeWidth={1.8} />,
            title: `Win rate trending up`,
            description: `Your 30-day win rate is ${a30.win_rate}% vs ${a90.win_rate}% over 90 days — your close process is improving.`,
            type: 'positive',
          })
        } else if (a30.win_rate < a90.win_rate && a90.win_rate > 0) {
          items.push({
            id: 'win-rate-down',
            icon: <AlertTriangle size={15} strokeWidth={1.8} />,
            title: `Win rate dipped recently`,
            description: `30-day win rate (${a30.win_rate}%) is below your 90-day average (${a90.win_rate}%). Review recent lost deals for patterns.`,
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

      if (staleLeads.status === 'fulfilled') {
        const twoWeeksAgo = new Date(Date.now() - 14 * 86400000).toISOString()
        const stale = staleLeads.value.results.filter(
          (l: Lead) => l.stage_moved_at && l.stage_moved_at < twoWeeksAgo
        )
        if (stale.length > 0) {
          const totalValue = stale.reduce((s: number, l: Lead) => s + (l.estimated_job_value ?? 0), 0)
          items.push({
            id: 'stale-leads',
            icon: <Users size={15} strokeWidth={1.8} />,
            title: `${stale.length} lead${stale.length !== 1 ? 's' : ''} going cold`,
            description: `${stale.length} contacted lead${stale.length !== 1 ? 's' : ''} with no activity in 14+ days${totalValue > 0 ? ` — worth ${fmtCurrency(totalValue)} in potential revenue` : ''}. Schedule follow-ups to keep them warm.`,
            type: 'action',
            link: '/dashboard',
            linkLabel: 'View leads',
          })
        }
      }

      if (stats.status === 'fulfilled') {
        const pipelineData = stats.value
        const topZips = Object.entries(pipelineData)
          .filter(([k]) => !['won', 'lost', 'not_interested'].includes(k))
        const totalActive = topZips.reduce((s, [, v]) => s + v.count, 0)
        const qualified = pipelineData['qualified']?.count ?? 0
        const quoteSent = pipelineData['quote_sent']?.count ?? 0
        const hotLeads = qualified + quoteSent
        if (hotLeads > 0) {
          items.push({
            id: 'hot-leads',
            icon: <Target size={15} strokeWidth={1.8} />,
            title: `${hotLeads} hot lead${hotLeads !== 1 ? 's' : ''} ready to close`,
            description: `You have ${qualified} qualified and ${quoteSent} quote-sent leads. Focus your energy here for fastest revenue.`,
            type: 'positive',
            link: '/pipeline',
            linkLabel: 'View pipeline',
          })
        }
      }

      if (ar.status === 'fulfilled') {
        const { total_overdue, overdue_count } = ar.value
        if (total_overdue > 0) {
          items.push({
            id: 'overdue-invoices',
            icon: <AlertTriangle size={15} strokeWidth={1.8} />,
            title: `${fmtCurrency(total_overdue)} in overdue invoices`,
            description: `${overdue_count} invoice${overdue_count !== 1 ? 's' : ''} past due. Send reminders to improve cash flow.`,
            type: 'warning',
            link: '/bookkeeping',
            linkLabel: 'View invoices',
          })
        }
      }

      if (counts.status === 'fulfilled' && counts.value.overdue > 3) {
        items.push({
          id: 'task-backlog',
          icon: <Zap size={15} strokeWidth={1.8} />,
          title: 'Task backlog growing',
          description: `${counts.value.overdue} overdue tasks. Consider delegating or rescheduling to stay on top of your pipeline.`,
          type: 'warning',
          link: '/tasks',
          linkLabel: 'View tasks',
        })
      }

      setInsights(items.slice(0, 4))
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
            <div key={i} style={{ height: 72, borderRadius: 'var(--radius-card)', background: 'white', boxShadow: 'var(--shadow-card)', opacity: 0.5 }} />
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
          const style = TYPE_STYLES[insight.type]
          return (
            <div
              key={insight.id}
              style={{
                display: 'flex', alignItems: 'flex-start', gap: 12,
                padding: '14px 16px',
                borderRadius: 'var(--radius-card)',
                background: style.bg,
                border: `1px solid ${style.border}`,
              }}
            >
              <div style={{
                width: 30, height: 30, borderRadius: 'var(--radius-button)',
                background: style.iconBg,
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
                    fontSize: 12, fontWeight: 500, color: style.iconBg,
                    textDecoration: 'none', whiteSpace: 'nowrap', flexShrink: 0,
                    alignSelf: 'center',
                  }}
                >
                  {insight.linkLabel} <ArrowRight size={12} strokeWidth={1.8} />
                </Link>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function fmtCurrency(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000)     return `$${(n / 1_000).toFixed(0)}k`
  return `$${n.toFixed(0)}`
}
