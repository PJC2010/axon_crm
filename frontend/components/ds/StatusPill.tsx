import React from 'react'
import { statusTokens } from '@/lib/gradeColors'

export interface StatusPillProps {
  status: string
  label?: string
  style?: React.CSSProperties
}

/**
 * Pipeline status pill — maps an Axon lead status key to its canonical color
 * and label. Pass `label` to override the displayed text.
 */
export function StatusPill({ status, label, style }: StatusPillProps) {
  const s = statusTokens(status)
  return (
    <span
      style={{
        display: 'inline-flex', alignItems: 'center',
        padding: '3px 10px', borderRadius: 'var(--radius-pill)',
        background: s.bg, color: s.fg,
        fontSize: 12, fontWeight: 500, lineHeight: 1.5, whiteSpace: 'nowrap', ...style,
      }}
    >
      {label || s.label}
    </span>
  )
}
