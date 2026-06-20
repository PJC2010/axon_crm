import React from 'react'

const STATUS: Record<string, { bg: string; fg: string; label: string }> = {
  new:            { bg: 'var(--color-ink-50)',     fg: 'var(--color-ink-500)',    label: 'New' },
  contacted:      { bg: 'var(--color-info-bg)',    fg: 'var(--color-info)',       label: 'Contacted' },
  qualified:      { bg: 'var(--color-accent-100)', fg: 'var(--color-accent-300)', label: 'Qualified' },
  quote_sent:     { bg: 'var(--color-gold-soft)',  fg: 'var(--color-gold)',       label: 'Quote Sent' },
  won:            { bg: 'var(--color-success-bg)', fg: 'var(--color-success)',    label: 'Won' },
  lost:           { bg: 'var(--color-danger-bg)',  fg: 'var(--color-danger)',     label: 'Lost' },
  not_interested: { bg: 'var(--color-ink-50)',     fg: 'var(--color-ink-400)',    label: 'Not Interested' },
  converted:      { bg: 'var(--color-success-bg)', fg: 'var(--color-success)',    label: 'Converted' },
}

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
  const s = STATUS[status] || STATUS.new
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
