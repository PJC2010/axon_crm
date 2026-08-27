'use client'
import React from 'react'

type Variant = 'primary' | 'secondary' | 'outlined' | 'minimal' | 'danger'
type Size = 'sm' | 'md' | 'lg'

const SIZES: Record<Size, React.CSSProperties & { gap: number; minHeight: number }> = {
  sm: { padding: '4px 10px', fontSize: 12, gap: 5, minHeight: 28 },
  md: { padding: '6px 14px', fontSize: 13, gap: 6, minHeight: 32 },
  lg: { padding: '10px 22px', fontSize: 15, gap: 8, minHeight: 44 },
}

const VARIANTS: Record<Variant, React.CSSProperties & Record<string, string>> = {
  primary: {
    background: 'var(--color-accent)',
    color: 'var(--text-on-accent)',
    border: '1px solid transparent',
    '--hover-bg': 'var(--color-accent-600)',
    '--active-bg': 'var(--color-accent-600)',
  },
  secondary: {
    background: 'var(--color-surface)',
    color: 'var(--color-ink-900)',
    border: '1px solid var(--color-ink-300)',
    '--hover-bg': 'var(--color-surface-hi)',
    '--active-bg': 'var(--color-surface-hi)',
  },
  outlined: {
    background: 'transparent',
    color: 'var(--color-ink-900)',
    border: '1px solid var(--color-ink-300)',
    '--hover-bg': 'var(--color-surface-hi)',
    '--active-bg': 'var(--color-surface-hi)',
  },
  minimal: {
    background: 'transparent',
    color: 'var(--color-ink-700)',
    border: '1px solid transparent',
    '--hover-bg': 'var(--color-surface-hi)',
    '--active-bg': 'var(--color-surface-hi)',
  },
  danger: {
    background: 'var(--color-danger)',
    color: 'var(--text-on-accent)',
    border: '1px solid transparent',
    '--hover-bg': 'color-mix(in srgb, var(--color-danger) 85%, #fff)',
    '--active-bg': 'color-mix(in srgb, var(--color-danger) 78%, #fff)',
  },
}

export interface ButtonProps extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  variant?: Variant
  size?: Size
  icon?: React.ReactNode
  endIcon?: React.ReactNode
  fill?: boolean
  children?: React.ReactNode
}

/** Axon primary button. Turquoise filled with an ink label (AA contrast);
 *  filled variants brighten on hover and depress 1px on press. */
export function Button({
  variant = 'primary',
  size = 'md',
  icon,
  endIcon,
  fill = false,
  disabled = false,
  children,
  style,
  className,
  ...rest
}: ButtonProps) {
  const s = SIZES[size] || SIZES.md
  const v = VARIANTS[variant] || VARIANTS.primary
  const [hover, setHover] = React.useState(false)
  const [active, setActive] = React.useState(false)

  return (
    <button
      className={className ? `ds-btn ${className}` : 'ds-btn'}
      disabled={disabled}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => { setHover(false); setActive(false) }}
      onMouseDown={() => setActive(true)}
      onMouseUp={() => setActive(false)}
      style={{
        display: fill ? 'flex' : 'inline-flex',
        width: fill ? '100%' : undefined,
        alignItems: 'center',
        justifyContent: 'center',
        gap: s.gap,
        padding: s.padding,
        minHeight: s.minHeight,
        fontFamily: 'var(--font-sans)',
        fontSize: s.fontSize,
        fontWeight: 500,
        lineHeight: 1,
        whiteSpace: 'nowrap',
        borderRadius: 'var(--radius-button)',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.4 : 1,
        transform: active && !disabled ? 'translateY(1px)' : 'none',
        transition: 'background var(--dur-base), border-color var(--dur-base), transform var(--dur-fast)',
        ...v,
        background: !disabled && active ? v['--active-bg']
          : !disabled && hover ? v['--hover-bg']
          : (v.background as string),
        ...style,
      }}
      {...rest}
    >
      {icon}
      {children}
      {endIcon}
    </button>
  )
}
