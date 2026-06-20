'use client'
import React from 'react'

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string
  leftIcon?: React.ReactNode
  fill?: boolean
  invalid?: boolean
}

/**
 * Axon text input. Slate fill, crisp 4px radius, turquoise focus ring.
 * Pass `label` to render a paired uppercase field label.
 */
export function Input({
  label,
  leftIcon,
  fill = false,
  invalid = false,
  style,
  id,
  ...rest
}: InputProps) {
  const [focus, setFocus] = React.useState(false)
  const inputId = id || (label ? `in-${label.replace(/\s+/g, '-').toLowerCase()}` : undefined)
  const field = (
    <div style={{ position: 'relative', display: fill ? 'block' : 'inline-block', width: fill ? '100%' : undefined }}>
      {leftIcon && (
        <span style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--color-ink-400)', display: 'flex' }}>
          {leftIcon}
        </span>
      )}
      <input
        id={inputId}
        onFocus={() => setFocus(true)}
        onBlur={() => setFocus(false)}
        style={{
          width: fill ? '100%' : undefined,
          fontFamily: 'var(--font-sans)',
          fontSize: 13,
          padding: leftIcon ? '8px 10px 8px 32px' : '8px 10px',
          borderRadius: 'var(--radius-input)',
          border: `1px solid ${invalid ? 'var(--color-danger)' : focus ? 'var(--color-accent)' : 'var(--color-ink-200)'}`,
          background: 'var(--color-surface)',
          color: 'var(--color-ink-900)',
          lineHeight: 1.4,
          boxShadow: focus ? 'var(--ring-accent)' : 'none',
          outline: 'none',
          transition: 'border-color var(--dur-base), box-shadow var(--dur-base)',
          ...style,
        }}
        {...rest}
      />
    </div>
  )
  if (!label) return field
  return (
    <label htmlFor={inputId} style={{ display: 'block' }}>
      <span className="t-label" style={{ marginBottom: 6 }}>{label}</span>
      {field}
    </label>
  )
}
