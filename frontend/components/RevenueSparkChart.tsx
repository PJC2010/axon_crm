'use client'
import { useEffect, useState, useCallback } from 'react'
import { getPnL } from '@/lib/api'
import type { PnLMonth } from '@/lib/types'

const MONTH_ABBR = ['J','F','M','A','M','J','J','A','S','O','N','D']

interface Props {
  year: number
  height?: number
}

export function RevenueSparkChart({ year, height = 160 }: Props) {
  const [months, setMonths] = useState<PnLMonth[]>([])
  const [loading, setLoading] = useState(true)
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const report = await getPnL(year)
      const monthMap = new Map(report.months.map(m => [m.month, m]))
      const currentMonth = new Date().getMonth() + 1
      const all = Array.from({ length: 12 }, (_, i) =>
        monthMap.get(i + 1) ?? { year, month: i + 1, revenue: 0, expenses: 0, net: 0 }
      ).filter(m => m.month <= currentMonth || m.revenue > 0 || m.expenses > 0)
      setMonths(all)
    } catch { /* silently fail */ }
    finally { setLoading(false) }
  }, [year])

  useEffect(() => { load() }, [load])

  if (loading) {
    return (
      <div style={{ height, borderRadius: 'var(--radius-card)', background: 'var(--color-surface)', boxShadow: 'var(--shadow-card)', opacity: 0.5 }} />
    )
  }

  if (months.length === 0) return null

  const W = 100
  const H = 100
  const padX = 6
  const padTop = 12
  const padBot = 18
  const chartH = H - padTop - padBot
  const maxVal = Math.max(...months.flatMap(m => [m.revenue, m.expenses]), 1)

  const revenuePoints = months.map((m, i) => ({
    x: padX + (i / Math.max(months.length - 1, 1)) * (W - 2 * padX),
    y: padTop + chartH - (m.revenue / maxVal) * chartH,
  }))
  const expensePoints = months.map((m, i) => ({
    x: padX + (i / Math.max(months.length - 1, 1)) * (W - 2 * padX),
    y: padTop + chartH - (m.expenses / maxVal) * chartH,
  }))

  const revLine = revenuePoints.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ')
  const revArea = `${revLine} L${revenuePoints[revenuePoints.length-1].x},${padTop + chartH} L${revenuePoints[0].x},${padTop + chartH} Z`
  const expLine = expensePoints.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ')

  const totalRevenue = months.reduce((s, m) => s + m.revenue, 0)
  const totalExpenses = months.reduce((s, m) => s + m.expenses, 0)
  const netProfit = totalRevenue - totalExpenses

  return (
    <div style={{
      background: 'var(--color-surface)', borderRadius: 'var(--radius-card)',
      boxShadow: 'var(--shadow-card)', padding: '16px 18px',
      position: 'relative',
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 8 }}>
        <div>
          <span className="t-eyebrow" style={{ marginBottom: 4, display: 'block' }}>Revenue Trend</span>
          <span style={{ fontSize: 22, fontWeight: 700, fontFamily: 'var(--font-display)', color: 'var(--color-ink-900)' }}>
            {fmtCurrency(totalRevenue)}
          </span>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 11, color: 'var(--color-ink-400)', marginBottom: 2 }}>Net Profit</div>
          <div style={{
            fontSize: 15, fontWeight: 700, fontFamily: 'var(--font-mono)',
            color: netProfit >= 0 ? 'var(--color-moss)' : 'var(--color-danger)',
          }}>
            {netProfit >= 0 ? '+' : ''}{fmtCurrency(netProfit)}
          </div>
        </div>
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: '100%', height, display: 'block' }}
        preserveAspectRatio="none"
        onMouseLeave={() => setHoveredIdx(null)}
      >
        <defs>
          <linearGradient id="revGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-moss)" stopOpacity="0.25" />
            <stop offset="100%" stopColor="var(--color-moss)" stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {[0.25, 0.5, 0.75].map(pct => (
          <line
            key={pct}
            x1={padX} y1={padTop + chartH * (1 - pct)}
            x2={W - padX} y2={padTop + chartH * (1 - pct)}
            stroke="var(--color-ink-100)" strokeWidth="0.3"
          />
        ))}

        <path d={revArea} fill="url(#revGrad)" />
        <path d={revLine} fill="none" stroke="var(--color-moss)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        <path d={expLine} fill="none" stroke="var(--color-rose)" strokeWidth="1" strokeDasharray="2,2" strokeLinecap="round" />

        {months.map((_, i) => (
          <text
            key={i}
            x={revenuePoints[i].x}
            y={H - 4}
            textAnchor="middle"
            fill="var(--color-ink-400)"
            fontSize="3.5"
            fontFamily="var(--font-sans)"
          >
            {MONTH_ABBR[months[i].month - 1]}
          </text>
        ))}

        {months.map((m, i) => (
          <rect
            key={`hover-${i}`}
            x={revenuePoints[i].x - (W / months.length) / 2}
            y={padTop}
            width={W / months.length}
            height={chartH}
            fill="transparent"
            onMouseEnter={() => setHoveredIdx(i)}
            style={{ cursor: 'crosshair' }}
          />
        ))}

        {hoveredIdx !== null && (
          <>
            <line
              x1={revenuePoints[hoveredIdx].x} y1={padTop}
              x2={revenuePoints[hoveredIdx].x} y2={padTop + chartH}
              stroke="var(--color-ink-300)" strokeWidth="0.3" strokeDasharray="1,1"
            />
            <circle cx={revenuePoints[hoveredIdx].x} cy={revenuePoints[hoveredIdx].y} r="2" fill="var(--color-moss)" stroke="white" strokeWidth="0.8" />
            <circle cx={expensePoints[hoveredIdx].x} cy={expensePoints[hoveredIdx].y} r="1.5" fill="var(--color-rose)" stroke="white" strokeWidth="0.6" />
          </>
        )}
      </svg>

      {hoveredIdx !== null && (
        <div style={{
          position: 'absolute', bottom: 8, left: '50%', transform: 'translateX(-50%)',
          background: 'var(--color-black)', color: 'var(--color-ink-900)', borderRadius: 'var(--radius-button)',
          padding: '5px 10px', fontSize: 11, whiteSpace: 'nowrap', display: 'flex', gap: 12,
          boxShadow: 'var(--shadow-pop)',
        }}>
          <span style={{ color: '#8FC98A' }}>Rev: {fmtCurrency(months[hoveredIdx].revenue)}</span>
          <span style={{ color: '#E8959E' }}>Exp: {fmtCurrency(months[hoveredIdx].expenses)}</span>
          <span style={{ fontWeight: 600 }}>Net: {fmtCurrency(months[hoveredIdx].net)}</span>
        </div>
      )}

      <div style={{ display: 'flex', gap: 14, marginTop: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--color-ink-500)' }}>
          <div style={{ width: 14, height: 2, background: 'var(--color-moss)', borderRadius: 1 }} /> Revenue
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--color-ink-500)' }}>
          <div style={{ width: 14, height: 2, background: 'var(--color-rose)', borderRadius: 1, borderTop: '1px dashed var(--color-rose)' }} /> Expenses
        </div>
      </div>
    </div>
  )
}

function fmtCurrency(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000)     return `$${(n / 1_000).toFixed(1)}k`
  return `$${n.toFixed(0)}`
}
