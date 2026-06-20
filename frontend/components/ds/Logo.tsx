import React from 'react'

export interface LogoProps {
  size?: number
  showWordmark?: boolean
  color?: string
  style?: React.CSSProperties
}

/**
 * Axon logo — the diamond "axon" mark (cross-cut node with a center dot) plus
 * the Roboto Slab wordmark. The mark fills with the turquoise accent.
 */
export function Logo({ size = 28, showWordmark = true, color = 'var(--color-accent)', style }: LogoProps) {
  const uid = React.useId().replace(/:/g, '')
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: size * 0.3, ...style }}>
      <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-label="Axon" role="img">
        <mask id={`axon-${uid}`}>
          <rect width="32" height="32" fill="white" />
          <rect x="2" y="14.5" width="28" height="3" rx="1.5" fill="black" />
          <rect x="14.5" y="2" width="3" height="28" rx="1.5" fill="black" />
        </mask>
        <polygon points="16,5 27,16 16,27 5,16" fill={color} mask={`url(#axon-${uid})`} />
        <circle cx="16" cy="16" r="1.5" fill="var(--color-ink-900)" />
      </svg>
      {showWordmark && (
        <span style={{
          fontFamily: 'var(--font-display)',
          fontSize: size * 0.72,
          fontWeight: 600,
          letterSpacing: '-0.01em',
          color: 'var(--color-ink-900)',
        }}>
          Axon
        </span>
      )}
    </span>
  )
}
