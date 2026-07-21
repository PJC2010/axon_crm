'use client'
import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, AlertCircle, X } from 'lucide-react'

export type ToastVariant = 'success' | 'error'

export interface ToastData {
  id: number
  message: string
  variant: ToastVariant
}

interface Props {
  toasts: ToastData[]
  onDismiss: (id: number) => void
}

export function ToastStack({ toasts, onDismiss }: Props) {
  if (toasts.length === 0) return null
  return (
    <div
      style={{
        position: 'fixed', bottom: 24, right: 24,
        zIndex: 400,
        display: 'flex', flexDirection: 'column', gap: 8,
        pointerEvents: 'none',
      }}
    >
      {toasts.map(t => (
        <ToastItem key={t.id} toast={t} onDismiss={onDismiss} />
      ))}
    </div>
  )
}

function ToastItem({ toast, onDismiss }: { toast: ToastData; onDismiss: (id: number) => void }) {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const show = requestAnimationFrame(() => setVisible(true))
    const hide = setTimeout(() => {
      setVisible(false)
      setTimeout(() => onDismiss(toast.id), 250)
    }, 3500)
    return () => { cancelAnimationFrame(show); clearTimeout(hide) }
  }, [toast.id, onDismiss])

  const isSuccess = toast.variant === 'success'
  return (
    <div
      style={{
        pointerEvents: 'all',
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '10px 14px',
        background: 'var(--color-surface)',
        border: `1px solid ${isSuccess ? 'var(--color-success-bg)' : 'var(--color-danger-bg)'}`,
        borderLeft: `3px solid ${isSuccess ? 'var(--color-success)' : 'var(--color-danger)'}`,
        borderRadius: 'var(--radius-card)',
        boxShadow: 'var(--shadow-pop)',
        fontSize: 13,
        color: 'var(--color-ink-900)',
        minWidth: 240, maxWidth: 340,
        opacity: visible ? 1 : 0,
        transform: visible ? 'translateY(0)' : 'translateY(8px)',
        transition: 'opacity 200ms, transform 200ms',
      }}
    >
      {isSuccess
        ? <CheckCircle2 size={15} color="var(--color-success)" strokeWidth={1.75} style={{ flexShrink: 0 }} />
        : <AlertCircle  size={15} color="var(--color-danger)"  strokeWidth={1.75} style={{ flexShrink: 0 }} />
      }
      <span style={{ flex: 1 }}>{toast.message}</span>
      <button
        onClick={() => onDismiss(toast.id)}
        aria-label="Dismiss"
        style={{
          background: 'none', border: 'none',
          cursor: 'pointer', color: 'var(--color-ink-400)',
          // 44px effective touch target without inflating the toast's chrome.
          width: 44, height: 44, margin: '-12px -14px -12px -8px',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexShrink: 0,
        }}
      >
        <X size={13} />
      </button>
    </div>
  )
}

/* Minimal hook — no global context needed; call in top-level page components */
let _nextId = 1
export function useToast() {
  const [toasts, setToasts] = useState<ToastData[]>([])

  // Stable identities: consumers feed `show`/`dismiss` into useCallback/useEffect
  // dependency arrays (e.g. a `load` callback driven by `[load]`). Recreating
  // these functions every render would invalidate those memos on every render,
  // producing an infinite render+fetch loop that crashes the tab.
  const show = useCallback((message: string, variant: ToastVariant = 'success') => {
    const id = _nextId++
    setToasts(prev => [...prev, { id, message, variant }])
  }, [])

  const dismiss = useCallback((id: number) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  return { toasts, show, dismiss }
}
