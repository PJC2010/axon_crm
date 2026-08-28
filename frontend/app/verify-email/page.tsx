'use client'
import { Suspense, useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { verifyEmail } from '@/lib/api'
import { Logo, Card, Button } from '@/components/ds'
import { isLoggedIn } from '@/lib/auth'

function VerifyEmailInner() {
  const token = useSearchParams().get('token')
  // No token in the URL is a dead link from the start — skip the 'working' state.
  const [state, setState] = useState<'working' | 'ok' | 'bad'>(token ? 'working' : 'bad')

  useEffect(() => {
    if (!token) return
    verifyEmail(token)
      .then(() => setState('ok'))
      .catch(() => setState('bad'))
  }, [token])

  const dest = isLoggedIn() ? '/home' : '/login'

  return (
    <div
      style={{
        minHeight: '100dvh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'transparent',
        padding: 20,
      }}
    >
      <Card elevation={2} padding={0} style={{ width: '100%', maxWidth: 380 }}>
        <div style={{ padding: '36px 32px', textAlign: 'center' }}>
          <div style={{ marginBottom: 26 }}>
            <Logo size={26} />
          </div>
          {state === 'working' && (
            <p style={{ fontSize: 14, color: 'var(--color-ink-700)' }}>Verifying your email…</p>
          )}
          {state === 'ok' && (
            <>
              <h1 className="t-title" style={{ fontSize: 18, margin: '0 0 10px' }}>Email verified</h1>
              <p style={{ fontSize: 13, color: 'var(--color-ink-500)', margin: '0 0 22px' }}>
                You&apos;re all set — thanks for confirming.
              </p>
              <Button variant="primary" size="lg" fill onClick={() => (window.location.href = dest)}>
                Continue
              </Button>
            </>
          )}
          {state === 'bad' && (
            <>
              <h1 className="t-title" style={{ fontSize: 18, margin: '0 0 10px' }}>
                This link is invalid or expired
              </h1>
              <p style={{ fontSize: 13, color: 'var(--color-ink-500)', margin: '0 0 22px' }}>
                Sign in and request a fresh verification email from Settings.
              </p>
              <Button variant="primary" size="lg" fill onClick={() => (window.location.href = dest)}>
                {isLoggedIn() ? 'Back to Axon' : 'Go to sign in'}
              </Button>
            </>
          )}
        </div>
      </Card>
    </div>
  )
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={null}>
      <VerifyEmailInner />
    </Suspense>
  )
}
