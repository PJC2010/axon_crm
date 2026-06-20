'use client'
import { useEffect, useState, useCallback } from 'react'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import { getPnL } from '@/lib/api'
import type { PnLReport, PnLMonth } from '@/lib/types'

const MONTH_ABBR = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
function fmt(n: number) { return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }) }
function fmtK(n: number) {
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (Math.abs(n) >= 1_000)     return `$${(n / 1_000).toFixed(1)}k`
  return `$${n.toFixed(0)}`
}

interface Props { year: number }

export function PnLChart({ year }: Props) {
  const [report, setReport] = useState<PnLReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [hoveredMonth, setHoveredMonth] = useState<number | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try { setReport(await getPnL(year)) }
    finally { setLoading(false) }
  }, [year])

  useEffect(() => { load() }, [load])

  if (loading) return <div style={{ textAlign: 'center', padding: 40, color: 'var(--color-ink-400)' }}>Loading…</div>
  if (!report) return null

  const maxVal = Math.max(...report.months.flatMap(m => [m.revenue, m.expenses]), 1)
  const BAR_H = 140

  const monthMap = new Map(report.months.map(m => [m.month, m]))
  const allMonths: PnLMonth[] = Array.from({ length: 12 }, (_, i) => monthMap.get(i + 1) ?? { year, month: i + 1, revenue: 0, expenses: 0, net: 0 })

  const marginPct = report.total_revenue > 0 ? Math.round((report.net_profit / report.total_revenue) * 100) : 0
  const TrendIcon = report.net_profit > 0 ? TrendingUp : report.net_profit < 0 ? TrendingDown : Minus

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      {/* Annual totals — redesigned as gradient cards */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <div style={{
          flex: '1 1 140px', padding: '18px 20px', borderRadius: 'var(--radius-card)',
          background: 'linear-gradient(135deg, var(--color-success-bg) 0%, var(--color-moss-soft) 100%)',
          border: '1px solid color-mix(in srgb, var(--color-moss) 30%, transparent)',
        }}>
          <div style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--color-moss)', marginBottom: 6 }}>Revenue</div>
          <div style={{ fontSize: 24, fontWeight: 700, fontFamily: 'var(--font-display)', color: 'var(--color-ink-900)' }}>{fmt(report.total_revenue)}</div>
        </div>
        <div style={{
          flex: '1 1 140px', padding: '18px 20px', borderRadius: 'var(--radius-card)',
          background: 'linear-gradient(135deg, var(--color-danger-bg) 0%, var(--color-rose-soft) 100%)',
          border: '1px solid color-mix(in srgb, var(--color-rose) 30%, transparent)',
        }}>
          <div style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--color-rose)', marginBottom: 6 }}>Expenses</div>
          <div style={{ fontSize: 24, fontWeight: 700, fontFamily: 'var(--font-display)', color: 'var(--color-ink-900)' }}>{fmt(report.total_expenses)}</div>
        </div>
        <div style={{
          flex: '1 1 140px', padding: '18px 20px', borderRadius: 'var(--radius-card)',
          background: report.net_profit >= 0
            ? 'linear-gradient(135deg, var(--color-accent-50) 0%, var(--color-ocean-soft) 100%)'
            : 'linear-gradient(135deg, var(--color-danger-bg) 0%, var(--color-rose-soft) 100%)',
          border: `1px solid ${report.net_profit >= 0 ? 'color-mix(in srgb, var(--color-accent) 35%, transparent)' : 'color-mix(in srgb, var(--color-rose) 30%, transparent)'}`,
        }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 6,
            fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.07em',
            color: report.net_profit >= 0 ? 'var(--color-accent)' : 'var(--color-danger)',
            marginBottom: 6,
          }}>
            <TrendIcon size={12} strokeWidth={2} />
            Net Profit · {marginPct}% margin
          </div>
          <div style={{ fontSize: 24, fontWeight: 700, fontFamily: 'var(--font-display)', color: 'var(--color-ink-900)' }}>{fmt(report.net_profit)}</div>
        </div>
      </div>

      {/* Bar chart */}
      <div>
        <div className="t-eyebrow" style={{ marginBottom: 12 }}>Monthly Breakdown</div>
        <div style={{
          background: 'var(--color-surface)', borderRadius: 'var(--radius-card)',
          boxShadow: 'var(--shadow-card)', padding: '16px 12px 8px',
          overflowX: 'auto',
        }}>
          <div style={{ display: 'flex', gap: 6, minWidth: 500, alignItems: 'flex-end', paddingBottom: 4 }}>
            {allMonths.map((m, idx) => {
              const revH = Math.round((m.revenue / maxVal) * BAR_H)
              const expH = Math.round((m.expenses / maxVal) * BAR_H)
              const hasData = m.revenue > 0 || m.expenses > 0
              const isHovered = hoveredMonth === idx
              return (
                <div
                  key={m.month}
                  style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, minWidth: 36, cursor: hasData ? 'pointer' : 'default' }}
                  onMouseEnter={() => setHoveredMonth(idx)}
                  onMouseLeave={() => setHoveredMonth(null)}
                >
                  {isHovered && hasData && (
                    <div style={{
                      fontSize: 9, fontWeight: 600, padding: '2px 5px',
                      borderRadius: 'var(--radius-button)', background: 'var(--color-black)', color: 'var(--color-ink-900)',
                      whiteSpace: 'nowrap', marginBottom: 2,
                    }}>
                      {fmtK(m.net)}
                    </div>
                  )}
                  <div style={{ display: 'flex', gap: 3, alignItems: 'flex-end', height: BAR_H }}>
                    <div title={`Revenue: ${fmt(m.revenue)}`} style={{
                      width: 14, height: revH || (hasData ? 2 : 0),
                      background: isHovered ? 'var(--color-moss)' : `color-mix(in srgb, var(--color-moss) ${hasData ? '85%' : '20%'}, transparent)`,
                      borderRadius: '4px 4px 0 0',
                      transition: 'height 0.4s ease, background 0.2s ease',
                    }} />
                    <div title={`Expenses: ${fmt(m.expenses)}`} style={{
                      width: 14, height: expH || (hasData ? 2 : 0),
                      background: isHovered ? 'var(--color-rose)' : `color-mix(in srgb, var(--color-rose) ${hasData ? '70%' : '20%'}, transparent)`,
                      borderRadius: '4px 4px 0 0',
                      transition: 'height 0.4s ease, background 0.2s ease',
                    }} />
                  </div>
                  <div style={{
                    fontSize: 10,
                    color: isHovered ? 'var(--color-ink-900)' : 'var(--color-ink-400)',
                    fontWeight: isHovered ? 600 : 400,
                    textAlign: 'center',
                    transition: 'color 0.15s ease',
                  }}>
                    {MONTH_ABBR[m.month - 1]}
                  </div>
                </div>
              )
            })}
          </div>

          {/* Legend */}
          <div style={{ display: 'flex', gap: 16, marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--color-ink-50)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--color-ink-500)' }}>
              <div style={{ width: 12, height: 12, background: 'var(--color-moss)', borderRadius: 3 }} /> Revenue
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--color-ink-500)' }}>
              <div style={{ width: 12, height: 12, background: 'var(--color-rose)', borderRadius: 3 }} /> Expenses
            </div>
          </div>
        </div>
      </div>

      {/* Monthly detail table */}
      {report.months.length > 0 && (
        <div>
          <div className="t-eyebrow" style={{ marginBottom: 8 }}>Detail</div>
          <div style={{
            background: 'var(--color-surface)', borderRadius: 'var(--radius-card)',
            boxShadow: 'var(--shadow-card)', overflow: 'hidden',
          }}>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid var(--color-ink-200)' }}>
                    {['Month', 'Revenue', 'Expenses', 'Net'].map(h => (
                      <th key={h} style={{ padding: '10px 14px', textAlign: h === 'Month' ? 'left' : 'right', color: 'var(--color-ink-400)', fontWeight: 600, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {report.months.map((m, idx) => (
                    <tr
                      key={m.month}
                      style={{
                        borderBottom: '1px solid var(--color-ink-100)',
                        background: hoveredMonth === (m.month - 1) ? 'var(--color-paper)' : 'transparent',
                        transition: 'background 0.15s ease',
                      }}
                      onMouseEnter={() => setHoveredMonth(m.month - 1)}
                      onMouseLeave={() => setHoveredMonth(null)}
                    >
                      <td style={{ padding: '10px 14px', color: 'var(--color-ink-700)', fontWeight: 500 }}>{MONTH_ABBR[m.month-1]} {m.year}</td>
                      <td className="tabular" style={{ padding: '10px 14px', textAlign: 'right', color: 'var(--color-moss)', fontWeight: 500 }}>{fmt(m.revenue)}</td>
                      <td className="tabular" style={{ padding: '10px 14px', textAlign: 'right', color: 'var(--color-rose)', fontWeight: 500 }}>{fmt(m.expenses)}</td>
                      <td className="tabular" style={{ padding: '10px 14px', textAlign: 'right', fontWeight: 700, color: m.net >= 0 ? 'var(--color-ink-900)' : 'var(--color-danger)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 6 }}>
                          {fmt(m.net)}
                          {m.net !== 0 && (
                            <span style={{
                              fontSize: 10, fontWeight: 600, padding: '1px 5px',
                              borderRadius: 'var(--radius-pill)',
                              background: m.net >= 0 ? 'var(--color-success-bg)' : 'var(--color-danger-bg)',
                              color: m.net >= 0 ? 'var(--color-moss)' : 'var(--color-danger)',
                            }}>
                              {m.net >= 0 ? '+' : ''}{Math.round((m.net / Math.max(m.revenue, 1)) * 100)}%
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr style={{ background: 'var(--color-paper)', borderTop: '2px solid var(--color-ink-200)' }}>
                    <td style={{ padding: '10px 14px', fontWeight: 700, color: 'var(--color-ink-900)' }}>Total</td>
                    <td className="tabular" style={{ padding: '10px 14px', textAlign: 'right', fontWeight: 700, color: 'var(--color-moss)' }}>{fmt(report.total_revenue)}</td>
                    <td className="tabular" style={{ padding: '10px 14px', textAlign: 'right', fontWeight: 700, color: 'var(--color-rose)' }}>{fmt(report.total_expenses)}</td>
                    <td className="tabular" style={{ padding: '10px 14px', textAlign: 'right', fontWeight: 700, color: report.net_profit >= 0 ? 'var(--color-accent)' : 'var(--color-danger)' }}>{fmt(report.net_profit)}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
