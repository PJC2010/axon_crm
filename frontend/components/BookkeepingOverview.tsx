'use client'
import { useEffect, useState, useCallback } from 'react'
import { getARSummary, getPnL } from '@/lib/api'
import type { ARSummary, PnLReport } from '@/lib/types'

function fmt(n: number) { return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }) }

const MONTH_ABBR = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

interface Props { year: number }

export function BookkeepingOverview({ year }: Props) {
  const [summary, setSummary]   = useState<ARSummary | null>(null)
  const [pnl, setPnl]           = useState<PnLReport | null>(null)
  const [loading, setLoading]   = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [s, p] = await Promise.all([getARSummary(year), getPnL(year)])
      setSummary(s); setPnl(p)
    } finally { setLoading(false) }
  }, [year])

  useEffect(() => { load() }, [load])

  if (loading) return <div style={{ textAlign: 'center', padding: 40, color: 'var(--color-ink-400)' }}>Loading…</div>
  if (!summary || !pnl) return null

  const netProfit = pnl.net_profit
  const BAR_H = 80
  const maxVal = Math.max(...pnl.months.flatMap(m => [m.revenue, m.expenses]), 1)
  const monthMap = new Map(pnl.months.map(m => [m.month, m]))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Top KPIs */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        {[
          { label: 'Revenue Collected', value: summary.total_collected, color: 'var(--color-moss)', sub: `${summary.invoice_count} invoices` },
          { label: 'Outstanding A/R', value: summary.total_outstanding, color: 'var(--color-ocean)', sub: summary.overdue_count > 0 ? `${summary.overdue_count} overdue` : 'All current' },
          { label: 'Total Expenses', value: pnl.total_expenses, color: 'var(--color-rose)', sub: 'All categories' },
          { label: 'Net Profit', value: netProfit, color: netProfit >= 0 ? 'var(--color-accent)' : 'var(--color-danger)', sub: `${pnl.total_revenue > 0 ? Math.round((netProfit / pnl.total_revenue) * 100) : 0}% margin` },
        ].map(card => (
          <div key={card.label} style={{ flex: '1 1 130px', padding: '16px', borderRadius: 'var(--radius-card)', border: '1px solid var(--color-ink-200)', background: 'var(--color-paper)', boxShadow: 'var(--shadow-card)' }}>
            <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.07em', color: card.color, marginBottom: 4 }}>{card.label}</div>
            <div style={{ fontSize: 22, fontWeight: 700, fontFamily: 'var(--font-display)', color: 'var(--color-ink-900)', lineHeight: 1 }}>{fmt(card.value)}</div>
            <div style={{ fontSize: 11, color: 'var(--color-ink-400)', marginTop: 4 }}>{card.sub}</div>
          </div>
        ))}
      </div>

      {/* Mini P&L chart */}
      {pnl.months.length > 0 && (
        <div style={{ padding: '16px', background: 'var(--color-paper)', borderRadius: 'var(--radius-card)', border: '1px solid var(--color-ink-200)' }}>
          <div className="t-eyebrow" style={{ marginBottom: 12 }}>Revenue vs. Expenses — {year}</div>
          <div style={{ overflowX: 'auto' }}>
            <div style={{ display: 'flex', gap: 6, minWidth: 400, alignItems: 'flex-end' }}>
              {Array.from({ length: 12 }, (_, i) => {
                const m = monthMap.get(i + 1)
                const rev = m?.revenue ?? 0
                const exp = m?.expenses ?? 0
                const revH = Math.round((rev / maxVal) * BAR_H)
                const expH = Math.round((exp / maxVal) * BAR_H)
                const hasData = rev > 0 || exp > 0
                return (
                  <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3, minWidth: 28 }}>
                    <div style={{ display: 'flex', gap: 2, alignItems: 'flex-end', height: BAR_H }}>
                      <div style={{ width: 10, height: revH || (hasData ? 2 : 0), background: 'var(--color-moss)', borderRadius: '2px 2px 0 0', opacity: hasData ? 1 : 0.15 }} />
                      <div style={{ width: 10, height: expH || (hasData ? 2 : 0), background: 'var(--color-rose)', borderRadius: '2px 2px 0 0', opacity: hasData ? 1 : 0.15 }} />
                    </div>
                    <div style={{ fontSize: 9, color: 'var(--color-ink-400)' }}>{MONTH_ABBR[i]}</div>
                  </div>
                )
              })}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 14, marginTop: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--color-ink-500)' }}>
              <div style={{ width: 10, height: 10, background: 'var(--color-moss)', borderRadius: 2 }} /> Revenue
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--color-ink-500)' }}>
              <div style={{ width: 10, height: 10, background: 'var(--color-rose)', borderRadius: 2 }} /> Expenses
            </div>
          </div>
        </div>
      )}

      {/* Overdue alert */}
      {summary.overdue_count > 0 && (
        <div style={{ padding: '14px 16px', background: 'rgba(180,60,60,0.06)', border: '1.5px solid var(--color-danger)', borderRadius: 'var(--radius-card)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontWeight: 600, color: 'var(--color-danger)', fontSize: 14 }}>⚠️ {summary.overdue_count} Overdue Invoice{summary.overdue_count > 1 ? 's' : ''}</div>
            <div style={{ fontSize: 13, color: 'var(--color-ink-500)', marginTop: 2 }}>{fmt(summary.total_overdue)} past due</div>
          </div>
          <div style={{ fontSize: 12, color: 'var(--color-ink-400)' }}>Check A/R tab →</div>
        </div>
      )}
    </div>
  )
}
