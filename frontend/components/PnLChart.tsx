'use client'
import { useEffect, useState, useCallback } from 'react'
import { getPnL } from '@/lib/api'
import type { PnLReport, PnLMonth } from '@/lib/types'

const MONTH_ABBR = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
function fmt(n: number) { return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }) }

interface Props { year: number }

export function PnLChart({ year }: Props) {
  const [report, setReport] = useState<PnLReport | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try { setReport(await getPnL(year)) }
    finally { setLoading(false) }
  }, [year])

  useEffect(() => { load() }, [load])

  if (loading) return <div style={{ textAlign: 'center', padding: 40, color: 'var(--color-ink-400)' }}>Loading…</div>
  if (!report) return null

  const maxVal = Math.max(...report.months.flatMap(m => [m.revenue, m.expenses]), 1)
  const BAR_H = 120

  // Fill all 12 months
  const monthMap = new Map(report.months.map(m => [m.month, m]))
  const allMonths: PnLMonth[] = Array.from({ length: 12 }, (_, i) => monthMap.get(i + 1) ?? { year, month: i + 1, revenue: 0, expenses: 0, net: 0 })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Annual totals */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        {[
          { label: 'Revenue', value: report.total_revenue, color: 'var(--color-moss)' },
          { label: 'Expenses', value: report.total_expenses, color: 'var(--color-rose)' },
          { label: 'Net Profit', value: report.net_profit, color: report.net_profit >= 0 ? 'var(--color-accent)' : 'var(--color-danger)' },
        ].map(card => (
          <div key={card.label} style={{ flex: '1 1 100px', padding: '14px 16px', borderRadius: 'var(--radius-card)', border: '1px solid var(--color-ink-200)', background: 'var(--color-paper)' }}>
            <div style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.07em', color: card.color, marginBottom: 4 }}>{card.label}</div>
            <div style={{ fontSize: 20, fontWeight: 700, fontFamily: 'var(--font-display)', color: 'var(--color-ink-900)' }}>{fmt(card.value)}</div>
          </div>
        ))}
      </div>

      {/* Bar chart — horizontally scrollable on mobile */}
      <div>
        <div className="t-eyebrow" style={{ marginBottom: 12 }}>Monthly Breakdown</div>
        <div style={{ overflowX: 'auto', paddingBottom: 4 }}>
          <div style={{ display: 'flex', gap: 8, minWidth: 480, alignItems: 'flex-end' }}>
            {allMonths.map(m => {
              const revH = Math.round((m.revenue / maxVal) * BAR_H)
              const expH = Math.round((m.expenses / maxVal) * BAR_H)
              const hasData = m.revenue > 0 || m.expenses > 0
              return (
                <div key={m.month} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, minWidth: 32 }}>
                  <div style={{ display: 'flex', gap: 2, alignItems: 'flex-end', height: BAR_H }}>
                    {/* Revenue bar */}
                    <div title={`Revenue: ${fmt(m.revenue)}`} style={{
                      width: 12, height: revH || (hasData ? 2 : 0),
                      background: 'var(--color-moss)', borderRadius: '3px 3px 0 0',
                      opacity: hasData ? 1 : 0.2, transition: 'height 0.4s ease',
                    }} />
                    {/* Expense bar */}
                    <div title={`Expenses: ${fmt(m.expenses)}`} style={{
                      width: 12, height: expH || (hasData ? 2 : 0),
                      background: 'var(--color-rose)', borderRadius: '3px 3px 0 0',
                      opacity: hasData ? 1 : 0.2, transition: 'height 0.4s ease',
                    }} />
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--color-ink-400)', textAlign: 'center' }}>{MONTH_ABBR[m.month - 1]}</div>
                  {m.net !== 0 && (
                    <div style={{ fontSize: 9, color: m.net >= 0 ? 'var(--color-moss)' : 'var(--color-danger)', fontWeight: 600 }}>
                      {m.net >= 0 ? '+' : ''}{Math.round(m.net / 1000)}k
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
        {/* Legend */}
        <div style={{ display: 'flex', gap: 16, marginTop: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--color-ink-500)' }}>
            <div style={{ width: 12, height: 12, background: 'var(--color-moss)', borderRadius: 2 }} /> Revenue
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--color-ink-500)' }}>
            <div style={{ width: 12, height: 12, background: 'var(--color-rose)', borderRadius: 2 }} /> Expenses
          </div>
        </div>
      </div>

      {/* Monthly detail table */}
      {report.months.length > 0 && (
        <div>
          <div className="t-eyebrow" style={{ marginBottom: 8 }}>Detail</div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--color-ink-200)' }}>
                  {['Month', 'Revenue', 'Expenses', 'Net'].map(h => (
                    <th key={h} style={{ padding: '6px 8px', textAlign: h === 'Month' ? 'left' : 'right', color: 'var(--color-ink-400)', fontWeight: 600, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {report.months.map(m => (
                  <tr key={m.month} style={{ borderBottom: '1px solid var(--color-ink-100)' }}>
                    <td style={{ padding: '8px', color: 'var(--color-ink-700)' }}>{MONTH_ABBR[m.month-1]} {m.year}</td>
                    <td className="tabular" style={{ padding: '8px', textAlign: 'right', color: 'var(--color-moss)', fontWeight: 500 }}>{fmt(m.revenue)}</td>
                    <td className="tabular" style={{ padding: '8px', textAlign: 'right', color: 'var(--color-rose)', fontWeight: 500 }}>{fmt(m.expenses)}</td>
                    <td className="tabular" style={{ padding: '8px', textAlign: 'right', fontWeight: 700, color: m.net >= 0 ? 'var(--color-ink-900)' : 'var(--color-danger)' }}>{fmt(m.net)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
