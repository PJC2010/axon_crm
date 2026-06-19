'use client'
import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { Sparkles, TrendingUp, Users, DollarSign, Clock, Target, ArrowRight, Plug } from 'lucide-react'
import { getMarketingInsights } from '@/lib/api'
import type { MarketingInsight, MarketingInsightsResponse } from '@/lib/types'

interface Props {
  days?: number
}

const TYPE_STYLES: Record<string, { bg: string; border: string; iconBg: string }> = {
  action:   { bg: 'var(--color-accent-50)', border: 'var(--color-accent-300)', iconBg: 'var(--color-accent)' },
  positive: { bg: 'var(--color-success-bg)',                border: 'var(--color-success)',                 iconBg: 'var(--color-moss)' },
  warning:  { bg: 'var(--color-warning-bg)',                border: 'var(--color-warning)',                 iconBg: 'var(--color-gold)' },
}

const CATEGORY_ICON: Record<string, React.ReactNode> = {
  content:    <Sparkles size={15} strokeWidth={1.8} />,
  audience:   <Users size={15} strokeWidth={1.8} />,
  paid:       <DollarSign size={15} strokeWidth={1.8} />,
  cadence:    <Clock size={15} strokeWidth={1.8} />,
  conversion: <Target size={15} strokeWidth={1.8} />,
}

export function MarketingInsightsPanel({ days = 90 }: Props) {
  const [data, setData] = useState<MarketingInsightsResponse | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setData(await getMarketingInsights(days))
    } catch {
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [days])

  useEffect(() => { load() }, [load])

  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
        <div style={{
          width: 24, height: 24, borderRadius: 'var(--radius-button)',
          background: 'linear-gradient(135deg, var(--color-accent), var(--color-ocean-d))',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <TrendingUp size={13} strokeWidth={1.8} color="white" />
        </div>
        <span className="t-eyebrow" style={{ letterSpacing: '0.1em' }}>Marketing Insights</span>
        <span style={{ fontSize: 10, color: 'var(--color-ink-400)', fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>
          From your social presence
        </span>
      </div>

      {loading ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {[1, 2, 3].map(i => (
            <div key={i} style={{ height: 84, borderRadius: 'var(--radius-card)', background: 'white', boxShadow: 'var(--shadow-card)', opacity: 0.5 }} />
          ))}
        </div>
      ) : !data || !data.has_data ? (
        <EmptyState />
      ) : data.insights.length === 0 ? (
        <p style={{ fontSize: 13, color: 'var(--color-ink-400)' }}>
          No insights yet — upload a more recent or complete export to generate recommendations.
        </p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {data.insights.map(insight => <InsightCard key={insight.id} insight={insight} />)}
        </div>
      )}
    </div>
  )
}

function InsightCard({ insight }: { insight: MarketingInsight }) {
  const s = TYPE_STYLES[insight.severity] ?? TYPE_STYLES.action
  const metric = insight.supporting_metric
  return (
    <div style={{ borderRadius: 'var(--radius-card)', background: s.bg, border: `1px solid ${s.border}`, overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, padding: '14px 16px' }}>
        <div style={{
          width: 30, height: 30, borderRadius: 'var(--radius-button)', background: s.iconBg,
          display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, marginTop: 1,
        }}>
          <span style={{ color: 'white', display: 'flex' }}>{CATEGORY_ICON[insight.category] ?? <Sparkles size={15} strokeWidth={1.8} />}</span>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <p style={{ margin: '0 0 3px', fontSize: 14, fontWeight: 600, color: 'var(--color-ink-900)', lineHeight: 1.3 }}>
            {insight.title}
          </p>
          <p style={{ margin: '0 0 6px', fontSize: 12.5, color: 'var(--color-ink-600)', lineHeight: 1.45 }}>
            {insight.message}
          </p>
          <p style={{ margin: 0, fontSize: 12.5, fontWeight: 500, color: s.iconBg, lineHeight: 1.4, display: 'flex', alignItems: 'center', gap: 5 }}>
            <ArrowRight size={12} strokeWidth={2} /> {insight.recommended_action}
          </p>
        </div>
        {metric?.value != null && (
          <div style={{ flexShrink: 0, textAlign: 'right', alignSelf: 'center' }}>
            <p style={{ margin: 0, fontSize: 15, fontWeight: 700, color: 'var(--color-ink-900)' }}>{metric.value}</p>
            {metric.comparison && (
              <p style={{ margin: 0, fontSize: 10.5, color: 'var(--color-ink-400)' }}>{metric.comparison}</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, textAlign: 'center',
      padding: '32px 20px', borderRadius: 'var(--radius-card)', background: 'white',
      boxShadow: 'var(--shadow-card)', border: '1px dashed var(--color-ink-200)',
    }}>
      <Plug size={22} strokeWidth={1.5} color="var(--color-accent)" />
      <p style={{ margin: 0, fontSize: 14, fontWeight: 600, color: 'var(--color-ink-900)' }}>Connect a source to see insights</p>
      <p style={{ margin: 0, fontSize: 13, color: 'var(--color-ink-500)', maxWidth: 360 }}>
        Connect Facebook or Instagram and upload an export, and Axon will analyze your reach,
        content, and ad spend to recommend ways to win more customers.
      </p>
      <Link
        href="/settings"
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 6, marginTop: 4, padding: '7px 14px',
          borderRadius: 'var(--radius-pill)', background: 'var(--color-accent)', color: 'white',
          fontSize: 13, fontWeight: 500, textDecoration: 'none',
        }}
      >
        Connect an account <ArrowRight size={13} strokeWidth={1.8} />
      </Link>
    </div>
  )
}
