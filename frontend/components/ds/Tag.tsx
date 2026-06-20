import React from 'react'

type Intent = 'none' | 'primary' | 'success' | 'warning' | 'danger' | 'info'

const INTENTS: Record<Intent, { bg: string; fg: string }> = {
  none:    { bg: 'var(--color-ink-50)',     fg: 'var(--color-ink-600)' },
  primary: { bg: 'var(--color-accent-100)', fg: 'var(--color-accent-300)' },
  success: { bg: 'var(--color-success-bg)', fg: 'var(--color-success)' },
  warning: { bg: 'var(--color-gold-soft)',  fg: 'var(--color-gold)' },
  danger:  { bg: 'var(--color-danger-bg)',  fg: 'var(--color-danger)' },
  info:    { bg: 'var(--color-info-bg)',    fg: 'var(--color-info)' },
}

export interface TagProps extends React.HTMLAttributes<HTMLSpanElement> {
  intent?: Intent
  round?: boolean
  large?: boolean
  dot?: boolean
}

/**
 * Compact status/category tag. Soft tinted fill keyed to a semantic intent;
 * `round` for a pill, `dot` to prefix a status dot.
 */
export function Tag({
  intent = 'none',
  round = false,
  large = false,
  dot = false,
  children,
  style,
  ...rest
}: TagProps) {
  const c = INTENTS[intent] || INTENTS.none
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: large ? '4px 12px' : '2px 9px',
        borderRadius: round ? 'var(--radius-pill)' : 'var(--radius-input)',
        background: c.bg,
        color: c.fg,
        fontFamily: 'var(--font-sans)',
        fontSize: large ? 12 : 11,
        fontWeight: 600,
        lineHeight: 1.5,
        letterSpacing: '0.02em',
        whiteSpace: 'nowrap',
        ...style,
      }}
      {...rest}
    >
      {dot && (
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: c.fg, flexShrink: 0 }} />
      )}
      {children}
    </span>
  )
}
