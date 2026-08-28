'use client'
import React from 'react'

export interface EmptyStateProps {
  /** A lucide icon element. Rendered large and thin — it is texture, not a button. */
  icon?: React.ReactNode
  title: string
  /** One sentence saying what to do next. Capped at a readable measure. */
  hint?: React.ReactNode
  /** The one action that resolves the empty state. */
  action?: React.ReactNode
  /** `sm` for a panel section, `lg` for a full page or table body. */
  size?: 'sm' | 'lg'
  style?: React.CSSProperties
}

/**
 * The composed "nothing here yet" view. An empty list is the first thing a new
 * account sees, so it names the gap and offers the one action that fills it
 * instead of printing "No results".
 */
export function EmptyState({ icon, title, hint, action, size = 'lg', style }: EmptyStateProps) {
  const lg = size === 'lg'
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        textAlign: 'center',
        padding: lg ? '56px 20px' : '28px 16px',
        ...style,
      }}
    >
      {icon && (
        <span style={{ color: 'var(--color-ink-300)', marginBottom: lg ? 14 : 10, lineHeight: 0 }}>
          {icon}
        </span>
      )}
      <p
        style={{
          margin: 0,
          fontSize: lg ? 16 : 14,
          fontWeight: 600,
          color: 'var(--color-ink-700)',
          textWrap: 'balance',
        }}
      >
        {title}
      </p>
      {hint && (
        <p
          style={{
            margin: '6px 0 0',
            maxWidth: 340,
            fontSize: 13,
            lineHeight: 1.55,
            color: 'var(--color-ink-400)',
            textWrap: 'pretty',
          }}
        >
          {hint}
        </p>
      )}
      {action && <div style={{ marginTop: lg ? 18 : 14 }}>{action}</div>}
    </div>
  )
}

/** Same thing, sized to sit inside a `<tbody>` as a full-width row. */
export function EmptyRow({ colSpan, ...rest }: EmptyStateProps & { colSpan: number }) {
  return (
    <tr>
      <td colSpan={colSpan} style={{ padding: 0 }}>
        <EmptyState {...rest} />
      </td>
    </tr>
  )
}
