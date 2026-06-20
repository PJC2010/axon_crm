'use client'
import React from 'react'

const ELEVATIONS: Record<number, string> = {
  0: 'none',
  1: 'var(--shadow-card)',
  2: 'var(--shadow-pop)',
  3: 'var(--shadow-modal)',
}

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  elevation?: 0 | 1 | 2 | 3
  interactive?: boolean
  padding?: number | string
}

/**
 * Axon surface card — slate fill with the signature light inset-border + drop
 * shadow. Set `interactive` for a hover lift used on clickable cards.
 */
export function Card({
  elevation = 1,
  interactive = false,
  padding = 20,
  children,
  style,
  ...rest
}: CardProps) {
  const [hover, setHover] = React.useState(false)
  const base = ELEVATIONS[elevation] ?? ELEVATIONS[1]
  return (
    <div
      onMouseEnter={() => interactive && setHover(true)}
      onMouseLeave={() => interactive && setHover(false)}
      style={{
        background: 'var(--color-surface)',
        borderRadius: 'var(--radius-card)',
        boxShadow: interactive && hover ? 'var(--shadow-pop)' : base,
        padding,
        cursor: interactive ? 'pointer' : undefined,
        transition: 'box-shadow var(--dur-base), transform var(--dur-base)',
        transform: interactive && hover ? 'translateY(-1px)' : 'none',
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  )
}
