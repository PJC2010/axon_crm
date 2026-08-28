'use client'
import { Skeleton, EmptyState } from './ds'
import { useCallback, useEffect, useState } from 'react'
import { getPerformance } from '@/lib/api'
import type { PerformanceBreakdown as Breakdown, PerformanceBucket, PerformanceDimension } from '@/lib/types'

const DIMENSIONS: { id: PerformanceDimension; label: string }[] = [
  { id: 'source',   label: 'By source' },
  { id: 'rep',      label: 'By rep' },
  { id: 'vertical', label: 'By vertical' },
]

function fmtCurrency(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000)     return `$${(n / 1_000).toFixed(1)}k`
  return `$${n.toFixed(0)}`
}

export function PerformanceBreakdown() {
  const [dimension, setDimension] = useState<PerformanceDimension>('source')
  const [data, setData] = useState<Breakdown | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setData(await getPerformance(dimension))
    } catch {
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [dimension])

  useEffect(() => { load() }, [load])

  const buckets: PerformanceBucket[] = data?.buckets ?? []
  const maxRevenue = Math.max(...buckets.map(b => b.revenue), 1)

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14, flexWrap: 'wrap', gap: 8 }}>
        <p className="t-eyebrow" style={{ margin: 0 }}>Performance</p>
        <div style={{ display: 'flex', gap: 4 }}>
          {DIMENSIONS.map(d => (
            <button
              key={d.id}
              onClick={() => setDimension(d.id)}
              style={{
                padding: '6px 12px', fontSize: 12, fontWeight: dimension === d.id ? 600 : 500,
                borderRadius: 'var(--radius-pill)', cursor: 'pointer',
                border: '1px solid ' + (dimension === d.id ? 'var(--color-accent)' : 'var(--color-ink-300)'),
                background: dimension === d.id ? 'var(--color-accent)' : 'var(--color-surface)',
                color: dimension === d.id ? 'white' : 'var(--color-ink-700)',
              }}
            >
              {d.label}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <Skeleton h={180} radius="var(--radius-card)" />
      ) : buckets.length === 0 ? (
        <EmptyState size="sm" title="No data yet for this breakdown" hint="Work a few leads and the split shows up here." />
      ) : (
        <div style={{ background: 'var(--color-surface)', borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)', overflow: 'hidden' }}>
          <div style={{ display: 'flex', padding: '10px 14px', borderBottom: '1px solid var(--color-ink-100)', gap: 8 }}>
            <span style={{ flex: 2, ...HEAD }}>{dimension === 'rep' ? 'Rep' : dimension === 'source' ? 'Source' : 'Vertical'}</span>
            <span style={{ flex: 1, ...HEAD, textAlign: 'right' }}>Leads</span>
            <span style={{ flex: 1, ...HEAD, textAlign: 'right' }}>Won</span>
            <span style={{ flex: 1, ...HEAD, textAlign: 'right' }}>Win&nbsp;%</span>
            <span style={{ flex: 1.2, ...HEAD, textAlign: 'right' }}>Revenue</span>
          </div>
          {buckets.map(b => (
            <div key={b.bucket} style={{ position: 'relative', padding: '10px 14px', borderBottom: '1px solid var(--color-ink-50)' }}>
              <div style={{ position: 'absolute', inset: 0, width: `${(b.revenue / maxRevenue) * 100}%`, background: 'color-mix(in srgb, var(--color-accent) 7%, transparent)' }} />
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, position: 'relative' }}>
                <span style={{ flex: 2, fontSize: 13, fontWeight: 500, color: 'var(--color-ink-900)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{b.bucket}</span>
                <span className="tabular" style={{ flex: 1, fontSize: 13, color: 'var(--color-ink-600)', textAlign: 'right' }}>{b.leads}</span>
                <span className="tabular" style={{ flex: 1, fontSize: 13, color: 'var(--color-ink-600)', textAlign: 'right' }}>{b.won}</span>
                <span className="tabular" style={{ flex: 1, fontSize: 13, color: 'var(--color-ink-600)', textAlign: 'right' }}>{b.win_rate}%</span>
                <span className="tabular" style={{ flex: 1.2, fontSize: 13, fontWeight: 600, color: 'var(--color-moss)', textAlign: 'right' }}>{fmtCurrency(b.revenue)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const HEAD: React.CSSProperties = {
  fontSize: 10, fontWeight: 600, textTransform: 'uppercase',
  letterSpacing: '0.06em', color: 'var(--color-ink-400)',
}
