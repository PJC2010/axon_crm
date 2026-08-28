'use client'
import type { ExpenseSummary, ExpenseCategory } from '@/lib/types'

const CATEGORY_COLORS: Record<ExpenseCategory, string> = {
  fuel:          'var(--color-ocean)',
  materials:     'var(--color-moss)',
  meals:         'var(--color-gold)',
  tools:         'var(--color-plum)',
  advertising:   'var(--color-rose)',
  subcontractor: 'var(--color-ink-600)',
  office:        'var(--color-accent)',
  other:         'var(--color-ink-400)',
}

const CATEGORY_LABELS: Record<ExpenseCategory, string> = {
  fuel: 'Fuel', materials: 'Materials', meals: 'Meals', tools: 'Tools',
  advertising: 'Advertising', subcontractor: 'Subcontractor', office: 'Office', other: 'Other',
}

function fmt(n: number) {
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
}

interface Props {
  summary: ExpenseSummary
}

export function ExpenseSummaryBar({ summary }: Props) {
  const categories = Object.entries(summary.by_category) as [ExpenseCategory, number][]
  const sortedCats = categories.sort(([, a], [, b]) => b - a)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Totals row */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <div style={{
          flex: '1 1 140px', background: 'var(--color-accent)', borderRadius: 'var(--radius-card)',
          padding: '16px 20px', color: 'var(--text-on-accent)',
        }}>
          <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.07em', textTransform: 'uppercase', marginBottom: 4 }}>
            Total Spent
          </div>
          <div style={{ fontSize: 26, fontWeight: 700, fontFamily: 'var(--font-display)', lineHeight: 1 }}>
            {fmt(summary.total)}
          </div>
          <div style={{ fontSize: 12, opacity: 0.75, marginTop: 4 }}>{summary.count} expenses</div>
        </div>

        <div style={{
          flex: '1 1 140px', background: 'var(--color-moss)', borderRadius: 'var(--radius-card)',
          padding: '16px 20px', color: 'var(--text-on-accent)',
        }}>
          <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.07em', textTransform: 'uppercase', opacity: 0.8, marginBottom: 4 }}>
            Tax Deductible
          </div>
          <div style={{ fontSize: 26, fontWeight: 700, fontFamily: 'var(--font-display)', lineHeight: 1 }}>
            {fmt(summary.tax_deductible_total)}
          </div>
          <div style={{ fontSize: 12, opacity: 0.75, marginTop: 4 }}>
            {summary.total > 0 ? Math.round((summary.tax_deductible_total / summary.total) * 100) : 0}% of total
          </div>
        </div>
      </div>

      {/* Category breakdown */}
      {sortedCats.length > 0 && (
        <div>
          <div className="t-eyebrow" style={{ marginBottom: 8 }}>By Category</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {sortedCats.map(([cat, amount]) => {
              const pct = summary.total > 0 ? (amount / summary.total) * 100 : 0
              const color = CATEGORY_COLORS[cat] ?? 'var(--color-ink-400)'
              return (
                <div key={cat} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div style={{ width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                      <span style={{ fontSize: 13, color: 'var(--color-ink-700)' }}>{CATEGORY_LABELS[cat]}</span>
                      <span className="tabular" style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-ink-900)' }}>{fmt(amount)}</span>
                    </div>
                    <div style={{ height: 4, background: 'var(--color-ink-100)', borderRadius: 2, overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: '100%', transform: `scaleX(${pct / 100})`, transformOrigin: 'left', background: color, borderRadius: 2, transition: 'transform 0.4s ease' }} />
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
