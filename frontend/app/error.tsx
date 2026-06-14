'use client'
// Route-level error boundary. Without this, any uncaught render error in a page
// segment (e.g. /pipeline) bubbles to the root and blanks the whole app. This
// contains the failure to a recoverable panel and surfaces the real error
// message + digest so production crashes are diagnosable (minified prod builds
// otherwise hide the cause behind a generic message).
import { useEffect } from 'react'

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    // Surfaces the full stack in the browser console for debugging.
    console.error('Route error boundary caught:', error)
  }, [error])

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
        background: 'var(--color-paper)',
      }}
    >
      <div style={{ maxWidth: 480, textAlign: 'center' }}>
        <h1
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 20,
            fontWeight: 600,
            color: 'var(--color-ink-900)',
            margin: '0 0 8px',
          }}
        >
          Something went wrong
        </h1>
        <p style={{ fontSize: 14, color: 'var(--color-ink-500)', margin: '0 0 16px' }}>
          This section hit an error. The rest of the app is still available.
        </p>

        {/* The actual error — visible in production so the cause is reportable. */}
        <pre
          style={{
            textAlign: 'left',
            fontSize: 12,
            fontFamily: 'var(--font-mono)',
            color: 'var(--color-ink-700)',
            background: 'var(--color-surface)',
            border: '1px solid var(--color-ink-200)',
            borderRadius: 8,
            padding: 12,
            margin: '0 0 16px',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          {error.message || 'Unknown error'}
          {error.digest ? `\n\ndigest: ${error.digest}` : ''}
        </pre>

        <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
          <button
            onClick={reset}
            style={{
              padding: '8px 16px',
              fontSize: 13,
              fontWeight: 500,
              borderRadius: 'var(--radius-pill)',
              border: 'none',
              cursor: 'pointer',
              background: 'var(--color-accent)',
              color: 'white',
            }}
          >
            Try again
          </button>
          <a
            href="/home"
            style={{
              padding: '8px 16px',
              fontSize: 13,
              fontWeight: 500,
              borderRadius: 'var(--radius-pill)',
              border: '1px solid var(--color-ink-200)',
              cursor: 'pointer',
              background: 'var(--color-paper)',
              color: 'var(--color-ink-700)',
              textDecoration: 'none',
            }}
          >
            Go home
          </a>
        </div>
      </div>
    </div>
  )
}
