'use client'
import { Suspense, useState, FormEvent } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { requestPasswordReset, resetPassword } from '@/lib/api'
import { Logo, Card, Button, Input } from '@/components/ds'

// Two modes on one page: with no ?token= it asks for the email and sends the
// link; arriving FROM that link (?token=...) it asks for the new password.
function ResetPasswordInner() {
  const router = useRouter()
  const token = useSearchParams().get('token')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [loading, setLoading] = useState(false)

  async function handleRequest(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await requestPasswordReset(email)
      setDone(true)
    } catch {
      setError('Could not send the reset email — try again in a minute.')
    } finally {
      setLoading(false)
    }
  }

  async function handleReset(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (password.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }
    setLoading(true)
    try {
      await resetPassword(token!, password)
      setDone(true)
      setTimeout(() => router.push('/login'), 1800)
    } catch {
      setError('This link is invalid or has expired — request a new one.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'transparent',
        padding: 20,
      }}
    >
      <Card elevation={2} padding={0} style={{ width: '100%', maxWidth: 380 }}>
        <div style={{ padding: '36px 32px' }}>
          <div style={{ marginBottom: 26 }}>
            <Logo size={26} />
          </div>

          {token ? (
            <>
              <h1 className="t-title" style={{ fontSize: 18, margin: '0 0 22px' }}>
                Choose a new password
              </h1>
              {done ? (
                <p style={{ fontSize: 14, color: 'var(--color-ink-700)' }}>
                  Password updated — taking you to sign in…
                </p>
              ) : (
                <form onSubmit={handleReset}>
                  <div style={{ marginBottom: error ? 14 : 22 }}>
                    <Input
                      label="New password (8+ characters)"
                      type="password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      autoFocus
                      required
                      fill
                    />
                  </div>
                  {error && (
                    <p role="alert" style={{ margin: '0 0 18px', fontSize: 13, color: 'var(--color-danger)' }}>
                      {error}
                    </p>
                  )}
                  <Button type="submit" variant="primary" size="lg" fill disabled={loading}>
                    {loading ? 'Saving…' : 'Set new password'}
                  </Button>
                </form>
              )}
            </>
          ) : (
            <>
              <h1 className="t-title" style={{ fontSize: 18, margin: '0 0 22px' }}>
                Reset your password
              </h1>
              {done ? (
                <p style={{ fontSize: 14, color: 'var(--color-ink-700)' }}>
                  If that email has an account, a reset link is on its way. Check your inbox.
                </p>
              ) : (
                <form onSubmit={handleRequest}>
                  <div style={{ marginBottom: error ? 14 : 22 }}>
                    <Input
                      label="Email"
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="you@company.com"
                      autoFocus
                      required
                      fill
                    />
                  </div>
                  {error && (
                    <p role="alert" style={{ margin: '0 0 18px', fontSize: 13, color: 'var(--color-danger)' }}>
                      {error}
                    </p>
                  )}
                  <Button type="submit" variant="primary" size="lg" fill disabled={loading}>
                    {loading ? 'Sending…' : 'Email me a reset link'}
                  </Button>
                </form>
              )}
            </>
          )}

          <p style={{ fontSize: 12, color: 'var(--color-ink-400)', margin: '18px 0 0', textAlign: 'center' }}>
            <a href="/login" style={{ color: 'var(--color-accent)' }}>Back to sign in</a>
          </p>
        </div>
      </Card>
    </div>
  )
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ResetPasswordInner />
    </Suspense>
  )
}
