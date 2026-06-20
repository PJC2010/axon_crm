import React from 'react'

export interface KpiCardProps {
  icon?: React.ReactNode
  label: string
  value: React.ReactNode
  sub?: React.ReactNode
  delta?: number | string
  style?: React.CSSProperties
}

/**
 * Dashboard KPI tile — eyebrow label, large tabular value, sub-line, and the
 * signature turquoise gradient top-rule. Optional delta with up/down arrow.
 */
export function KpiCard({ icon, label, value, sub, delta, style }: KpiCardProps) {
  const positive = typeof delta === 'number' ? delta >= 0 : undefined
  return (
    <div
      style={{
        position: 'relative', overflow: 'hidden',
        background: 'var(--color-surface)',
        borderRadius: 'var(--radius-card)',
        boxShadow: 'var(--shadow-card)',
        padding: 16, minHeight: 88,
        ...style,
      }}
    >
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, height: 3,
        background: 'linear-gradient(90deg, var(--color-accent) 0%, var(--color-accent-300) 100%)',
        opacity: 0.7,
      }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
        {icon}
        <span className="t-eyebrow">{label}</span>
      </div>
      <p className="tabular" style={{ margin: '0 0 4px', fontSize: 26, fontWeight: 700, color: 'var(--color-ink-900)', lineHeight: 1 }}>
        {value}
      </p>
      {delta != null && (
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: 2,
          fontSize: 12, fontWeight: 600,
          color: positive ? 'var(--color-moss)' : 'var(--color-rose)',
        }}>
          {positive ? '▲' : '▼'} {typeof delta === 'number' ? Math.abs(delta) : delta}
        </span>
      )}
      {sub && <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--color-ink-400)' }}>{sub}</p>}
    </div>
  )
}
