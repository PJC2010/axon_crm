'use client'
import { useEffect } from 'react'
import { AlertTriangle, X } from 'lucide-react'

interface Props {
  title: string
  message: string
  confirmLabel?: string
  danger?: boolean
  loading?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmModal({
  title,
  message,
  confirmLabel = 'Confirm',
  danger = false,
  loading = false,
  onConfirm,
  onCancel,
}: Props) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onCancel()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onCancel])

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onCancel}
        style={{
          position: 'fixed', inset: 0,
          background: 'rgba(22,24,29,0.4)',
          backdropFilter: 'blur(2px)',
          zIndex: 300,
        }}
      />

      {/* Dialog */}
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        style={{
          position: 'fixed',
          top: '50%', left: '50%',
          transform: 'translate(-50%, -50%)',
          zIndex: 301,
          width: 'min(420px, calc(100vw - 32px))',
          background: 'var(--color-surface)',
          borderRadius: 'var(--radius-modal)',
          boxShadow: 'var(--shadow-modal)',
          padding: '24px',
        }}
      >
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 12 }}>
          {danger && (
            <span style={{
              flexShrink: 0,
              width: 36, height: 36,
              borderRadius: '50%',
              background: 'var(--color-danger-bg)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <AlertTriangle size={16} color="var(--color-danger)" strokeWidth={1.75} />
            </span>
          )}
          <div style={{ flex: 1 }}>
            <p id="confirm-title" style={{ margin: 0, fontSize: 15, fontWeight: 600, color: 'var(--color-ink-900)' }}>
              {title}
            </p>
            <p style={{ margin: '6px 0 0', fontSize: 13, color: 'var(--color-ink-500)', lineHeight: 1.5 }}>
              {message}
            </p>
          </div>
          <button
            onClick={onCancel}
            aria-label="Cancel"
            style={{
              flexShrink: 0,
              background: 'none', border: 'none',
              cursor: 'pointer', padding: 4,
              color: 'var(--color-ink-400)',
              display: 'flex',
            }}
          >
            <X size={16} />
          </button>
        </div>

        {/* Actions */}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 20 }}>
          <button
            onClick={onCancel}
            disabled={loading}
            className="btn-secondary"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={loading}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '6px 16px',
              borderRadius: 'var(--radius-button)',
              border: '1px solid transparent',
              background: danger ? 'var(--color-danger)' : 'var(--color-accent)',
              color: 'white',
              fontSize: 13, fontWeight: 500, cursor: loading ? 'not-allowed' : 'pointer',
              opacity: loading ? 0.65 : 1,
              transition: 'background 160ms',
            }}
          >
            {loading ? 'Working…' : confirmLabel}
          </button>
        </div>
      </div>
    </>
  )
}
