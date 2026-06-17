'use client'
import { useEffect, useState, useCallback } from 'react'
import { getJobCosting } from '@/lib/api'
import type { JobCostRow } from '@/lib/types'

function fmt(n: number) { return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }) }
function pct(n: number) { return n.toFixed(1) + '%' }

interface Props { year?: number }

export function JobCostingTable({ year }: Props) {
  const [rows, setRows]       = useState<JobCostRow[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try { setRows(await getJobCosting(year)) }
    finally { setLoading(false) }
  }, [year])

  useEffect(() => { load() }, [load])

  if (loading) return <div style={{ textAlign: 'center', padding: 40, color: 'var(--color-ink-400)' }}>Loading…</div>

  if (rows.length === 0) return (
    <div style={{ textAlign: 'center', padding: '60px 20px' }}>
      <div style={{ fontSize: 36, marginBottom: 10 }}>📊</div>
      <div style={{ fontWeight: 600, color: 'var(--color-ink-700)', marginBottom: 6 }}>No job data yet</div>
      <div style={{ fontSize: 14, color: 'var(--color-ink-400)' }}>Create invoices and expenses linked to leads to see job profitability</div>
    </div>
  )

  const totals = rows.reduce((acc, r) => ({
    estimated: acc.estimated + r.estimated_value,
    revenue: acc.revenue + r.revenue,
    amount_paid: acc.amount_paid + r.amount_paid,
    expenses: acc.expenses + r.expenses,
    profit: acc.profit + r.profit,
  }), { estimated: 0, revenue: 0, amount_paid: 0, expenses: 0, profit: 0 })
  const overallMargin = totals.amount_paid > 0 ? (totals.profit / totals.amount_paid) * 100 : 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Summary row */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        {[
          { label: 'Total Estimated', value: totals.estimated, color: 'var(--color-gold)' },
          { label: 'Total Invoiced', value: totals.revenue, color: 'var(--color-ocean)' },
          { label: 'Total Collected', value: totals.amount_paid, color: 'var(--color-moss)' },
          { label: 'Total Expenses', value: totals.expenses, color: 'var(--color-rose)' },
          { label: 'Net Profit', value: totals.profit, color: totals.profit >= 0 ? 'var(--color-accent)' : 'var(--color-danger)' },
        ].map(card => (
          <div key={card.label} style={{ flex: '1 1 100px', padding: '12px 14px', borderRadius: 'var(--radius-card)', border: '1px solid var(--color-ink-200)' }}>
            <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.07em', color: card.color, marginBottom: 3 }}>{card.label}</div>
            <div style={{ fontSize: 18, fontWeight: 700, fontFamily: 'var(--font-display)', color: 'var(--color-ink-900)' }}>{fmt(card.value)}</div>
          </div>
        ))}
      </div>

      {/* Overall margin */}
      <div style={{ padding: '12px 14px', background: 'var(--color-ink-50)', borderRadius: 'var(--radius-card)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 13, color: 'var(--color-ink-600)', fontWeight: 500 }}>Overall Profit Margin</span>
        <span style={{ fontSize: 16, fontWeight: 700, color: overallMargin >= 30 ? 'var(--color-moss)' : overallMargin >= 15 ? 'var(--color-gold)' : 'var(--color-danger)' }}>
          {pct(overallMargin)}
        </span>
      </div>

      {/* Per-job cards — mobile friendly */}
      <div>
        <div className="t-eyebrow" style={{ marginBottom: 10 }}>By Job</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {rows.map(row => {
            const marginColor = row.margin_pct >= 30 ? 'var(--color-moss)' : row.margin_pct >= 15 ? 'var(--color-gold)' : 'var(--color-danger)'
            return (
              <div key={row.property_id} style={{ padding: '14px 16px', background: 'var(--color-paper)', border: '1px solid var(--color-ink-200)', borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
                  <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--color-ink-900)', flex: 1, marginRight: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {row.address}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
                    <span style={{ fontSize: 13, fontWeight: 700, color: marginColor }}>{pct(row.margin_pct)}</span>
                    <span style={{ fontSize: 11, color: 'var(--color-ink-400)' }}>margin</span>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                  {[
                    { label: 'Estimated', value: row.estimated_value, color: 'var(--color-gold)' },
                    { label: 'Invoiced', value: row.revenue, color: 'var(--color-ink-600)' },
                    { label: 'Collected', value: row.amount_paid, color: 'var(--color-moss)' },
                    { label: 'Expenses', value: row.expenses, color: 'var(--color-rose)' },
                    { label: 'Profit', value: row.profit, color: row.profit >= 0 ? 'var(--color-accent)' : 'var(--color-danger)' },
                  ].map(col => (
                    <div key={col.label} style={{ flex: '1 1 60px' }}>
                      <div style={{ fontSize: 10, color: 'var(--color-ink-400)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>{col.label}</div>
                      <div className="tabular" style={{ fontSize: 13, fontWeight: 600, color: col.color }}>{fmt(col.value)}</div>
                    </div>
                  ))}
                </div>
                {/* Mini profit bar */}
                <div style={{ marginTop: 10, height: 4, background: 'var(--color-ink-100)', borderRadius: 2, overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${Math.min(Math.max(row.margin_pct, 0), 100)}%`, background: marginColor, borderRadius: 2, transition: 'width 0.4s ease' }} />
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
