'use client'
import { useEffect, useState, useCallback } from 'react'
import { AlertTriangle } from 'lucide-react'
import { getARSummary, getAgingReport } from '@/lib/api'
import type { ARSummary, AgingBucket } from '@/lib/types'

function fmt(n: number) { return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }) }

const BUCKET_COLORS = ['var(--color-moss)', 'var(--color-gold)', 'var(--color-rose)', 'var(--color-danger)', 'var(--color-danger)']

interface Props { year: number }

export function ARDashboard({ year }: Props) {
  const [summary, setSummary]   = useState<ARSummary | null>(null)
  const [aging, setAging]       = useState<AgingBucket[]>([])
  const [loading, setLoading]   = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [s, a] = await Promise.all([getARSummary(year), getAgingReport()])
      setSummary(s); setAging(a)
    } finally { setLoading(false) }
  }, [year])

  useEffect(() => { load() }, [load])

  if (loading) return <div style={{ textAlign: 'center', padding: 40, color: 'var(--color-ink-400)' }}>Loading…</div>
  if (!summary) return null

  const collectionRate = summary.total_invoiced > 0
    ? Math.round((summary.total_collected / summary.total_invoiced) * 100)
    : 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>

      {/* A/R KPI cards */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        {[
          { label: 'Outstanding', value: summary.total_outstanding, color: 'var(--color-ocean)', sub: `${summary.invoice_count} invoices` },
          { label: 'Overdue', value: summary.total_overdue, color: 'var(--color-danger)', sub: `${summary.overdue_count} overdue`, warn: summary.overdue_count > 0 },
          { label: 'Collected', value: summary.total_collected, color: 'var(--color-moss)', sub: `${collectionRate}% collection rate` },
        ].map(card => (
          <div key={card.label} style={{
            flex: '1 1 120px', padding: '16px', borderRadius: 'var(--radius-card)',
            border: card.warn ? `2px solid ${card.color}` : '1px solid var(--color-ink-200)',
            background: card.warn ? `${card.color}0d` : 'var(--color-paper)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              {card.warn && <AlertTriangle size={12} color={card.color} />}
              <span style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.07em', color: card.color }}>{card.label}</span>
            </div>
            <div style={{ fontSize: 22, fontWeight: 700, fontFamily: 'var(--font-display)', color: 'var(--color-ink-900)' }}>{fmt(card.value)}</div>
            <div style={{ fontSize: 12, color: 'var(--color-ink-400)', marginTop: 2 }}>{card.sub}</div>
          </div>
        ))}
      </div>

      {/* Aging buckets */}
      <div>
        <div className="t-eyebrow" style={{ marginBottom: 12 }}>A/R Aging</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {aging.map((bucket, i) => {
            const color = BUCKET_COLORS[i] ?? 'var(--color-ink-400)'
            const maxAmt = Math.max(...aging.map(b => b.amount), 1)
            const pct = (bucket.amount / maxAmt) * 100
            return (
              <div key={bucket.label} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{ width: 90, flexShrink: 0, fontSize: 12, color: 'var(--color-ink-600)', fontWeight: 500 }}>{bucket.label}</div>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <span style={{ fontSize: 12, color: 'var(--color-ink-500)' }}>{bucket.count} invoice{bucket.count !== 1 ? 's' : ''}</span>
                    <span className="tabular" style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-ink-900)' }}>{fmt(bucket.amount)}</span>
                  </div>
                  <div style={{ height: 6, background: 'var(--color-ink-100)', borderRadius: 3, overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: '100%', transform: `scaleX(${pct / 100})`, transformOrigin: 'left', background: color, borderRadius: 3, transition: 'transform 0.4s ease' }} />
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Collection rate bar */}
      <div style={{ padding: '16px', background: 'var(--color-ink-50)', borderRadius: 'var(--radius-card)', border: '1px solid var(--color-ink-200)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-ink-700)' }}>Collection Rate</span>
          <span style={{ fontSize: 13, fontWeight: 700, color: collectionRate >= 80 ? 'var(--color-moss)' : collectionRate >= 60 ? 'var(--color-gold)' : 'var(--color-danger)' }}>
            {collectionRate}%
          </span>
        </div>
        <div style={{ height: 8, background: 'var(--color-ink-200)', borderRadius: 4, overflow: 'hidden' }}>
          <div style={{
            height: '100%', width: '100%', transform: `scaleX(${collectionRate / 100})`, transformOrigin: 'left', borderRadius: 4, transition: 'transform 0.5s ease',
            background: collectionRate >= 80 ? 'var(--color-moss)' : collectionRate >= 60 ? 'var(--color-gold)' : 'var(--color-danger)',
          }} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, fontSize: 12, color: 'var(--color-ink-400)' }}>
          <span>Invoiced: {fmt(summary.total_invoiced)}</span>
          <span>Collected: {fmt(summary.total_collected)}</span>
        </div>
      </div>
    </div>
  )
}
