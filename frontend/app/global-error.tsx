'use client'
// Last-resort boundary for errors thrown in the root layout itself, which
// app/error.tsx cannot catch. Must render its own <html>/<body>.
import { useEffect } from 'react'

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error('Global error boundary caught:', error)
  }, [error])

  return (
    <html lang="en">
      <body style={{ fontFamily: 'system-ui, sans-serif', margin: 0 }}>
        <div
          style={{
            minHeight: '100dvh',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 24,
          }}
        >
          <div style={{ maxWidth: 480, textAlign: 'center' }}>
            <h1 style={{ fontSize: 20, fontWeight: 600, margin: '0 0 8px' }}>
              Something went wrong
            </h1>
            <pre
              style={{
                textAlign: 'left',
                fontSize: 12,
                background: '#f5f5f5',
                border: '1px solid #ddd',
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
            <button
              onClick={reset}
              style={{
                padding: '8px 16px',
                fontSize: 13,
                borderRadius: 9999,
                border: 'none',
                cursor: 'pointer',
                background: '#1a1a1a',
                color: 'white',
              }}
            >
              Try again
            </button>
          </div>
        </div>
      </body>
    </html>
  )
}
