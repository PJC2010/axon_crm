'use client'
import { useState, useEffect, useRef, FormEvent } from 'react'
import { useRouter } from 'next/navigation'
import { signup, getSignupStatus, loginWithGoogle, loginWithApple } from '@/lib/api'
import { setToken } from '@/lib/auth'
import { Logo, Card, Button, Input } from '@/components/ds'

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_OAUTH_CLIENT_ID
const APPLE_CLIENT_ID = process.env.NEXT_PUBLIC_APPLE_CLIENT_ID
const APPLE_REDIRECT_URI = process.env.NEXT_PUBLIC_APPLE_REDIRECT_URI

// Pull the human-readable reason out of an error thrown by lib/api's req()
// (same helper as the login page).
function reason(err: unknown, fallback: string): string {
  const msg = err instanceof Error ? err.message : String(err)
  const match = msg.match(/\{.*\}/)
  if (match) {
    try {
      const detail = JSON.parse(match[0]).detail
      if (typeof detail === 'string') return detail
    } catch {
      /* not JSON — fall through */
    }
  }
  return fallback
}

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[src="${src}"]`)) return resolve()
    const el = document.createElement('script')
    el.src = src
    el.async = true
    el.onload = () => resolve()
    el.onerror = () => reject(new Error(`Failed to load ${src}`))
    document.head.appendChild(el)
  })
}

export default function SignupPage() {
  const router = useRouter()
  const [company, setCompany] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [enabled, setEnabled] = useState(true)
  const googleBtn = useRef<HTMLDivElement>(null)

  function onTokenSuccess(access_token: string) {
    setToken(access_token)
    router.push('/home')
  }

  // Hide the form (with a pointer to sign-in) when the server runs invite-only.
  useEffect(() => {
    getSignupStatus()
      .then((s) => setEnabled(s.enabled))
      .catch(() => {}) // can't reach the API — leave the form up; submit will explain
  }, [])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const { access_token } = await signup(company, email, password)
      onTokenSuccess(access_token)
    } catch (err) {
      setError(reason(err, 'Could not create your account — try again.'))
    } finally {
      setLoading(false)
    }
  }

  // Google Identity Services: the same exchange as the login page — the backend
  // provisions a fresh workspace when the identity is new.
  useEffect(() => {
    if (!GOOGLE_CLIENT_ID || !enabled) return
    let cancelled = false
    loadScript('https://accounts.google.com/gsi/client')
      .then(() => {
        if (cancelled) return
        const g = (window as any).google
        if (!g || !googleBtn.current) return
        g.accounts.id.initialize({
          client_id: GOOGLE_CLIENT_ID,
          callback: async (resp: { credential: string }) => {
            setError(null)
            try {
              const { access_token } = await loginWithGoogle(resp.credential)
              onTokenSuccess(access_token)
            } catch (err) {
              setError(reason(err, 'Google sign-up failed'))
            }
          },
        })
        g.accounts.id.renderButton(googleBtn.current, {
          theme: 'outline',
          size: 'large',
          width: 316,
          text: 'signup_with',
        })
      })
      .catch(() => setError('Could not load Google sign-up'))
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled])

  useEffect(() => {
    if (!APPLE_CLIENT_ID || !APPLE_REDIRECT_URI || !enabled) return
    loadScript(
      'https://appleid.cdn-apple.com/appleauth/static/jsapi/appleid/1/en_US/appleid.auth.js',
    )
      .then(() => {
        const a = (window as any).AppleID
        if (!a) return
        a.auth.init({
          clientId: APPLE_CLIENT_ID,
          scope: 'name email',
          redirectURI: APPLE_REDIRECT_URI,
          usePopup: true,
        })
      })
      .catch(() => setError('Could not load Apple sign-up'))
  }, [enabled])

  async function handleApple() {
    setError(null)
    try {
      const a = (window as any).AppleID
      const res = await a.auth.signIn()
      const idToken = res?.authorization?.id_token
      if (!idToken) throw new Error('No Apple token returned')
      const { access_token } = await loginWithApple(idToken)
      onTokenSuccess(access_token)
    } catch (err) {
      setError(reason(err, 'Apple sign-up was cancelled or failed'))
    }
  }

  const showSocial = Boolean(GOOGLE_CLIENT_ID) || Boolean(APPLE_CLIENT_ID && APPLE_REDIRECT_URI)

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
      <Card elevation={2} padding={0} style={{ width: '100%', maxWidth: 400 }}>
        <div style={{ padding: '36px 32px' }}>
          <div style={{ marginBottom: 26 }}>
            <Logo size={26} />
          </div>

          {!enabled ? (
            <>
              <h1 className="t-title" style={{ fontSize: 18, margin: '0 0 12px' }}>
                Signup is invite-only right now
              </h1>
              <p style={{ fontSize: 13, color: 'var(--color-ink-500)', margin: '0 0 18px' }}>
                Ask your administrator for an invite, or sign in if you already have an account.
              </p>
              <Button variant="primary" size="lg" fill onClick={() => router.push('/login')}>
                Go to sign in
              </Button>
            </>
          ) : (
            <>
              <h1 className="t-title" style={{ fontSize: 18, margin: '0 0 6px' }}>
                Create your workspace
              </h1>
              <p style={{ fontSize: 13, color: 'var(--color-ink-500)', margin: '0 0 22px' }}>
                Free for 14 days. No credit card, no contract — cancel anytime.
              </p>

              <form onSubmit={handleSubmit}>
                <div style={{ marginBottom: 14 }}>
                  <Input
                    label="Company or business name"
                    value={company}
                    onChange={(e) => setCompany(e.target.value)}
                    placeholder="Spring Exterior Services"
                    autoFocus
                    required
                    fill
                  />
                </div>
                <div style={{ marginBottom: 14 }}>
                  <Input
                    label="Work email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@company.com"
                    required
                    fill
                  />
                </div>
                <div style={{ marginBottom: error ? 14 : 22 }}>
                  <Input
                    label="Password (8+ characters)"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    fill
                  />
                </div>

                {error && (
                  <p
                    role="alert"
                    style={{
                      margin: '0 0 18px',
                      padding: '8px 12px',
                      borderRadius: 'var(--radius-input)',
                      background: 'var(--color-danger-bg)',
                      border: '1px solid color-mix(in srgb, var(--color-danger) 30%, transparent)',
                      color: 'var(--color-danger)',
                      fontSize: 13,
                    }}
                  >
                    {error}
                  </p>
                )}

                <Button type="submit" variant="primary" size="lg" fill disabled={loading}>
                  {loading ? 'Creating your workspace…' : 'Create account'}
                </Button>
              </form>

              {showSocial && (
                <>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 10,
                      margin: '20px 0 16px',
                      color: 'var(--color-ink-300)',
                      fontSize: 12,
                    }}
                  >
                    <span style={{ flex: 1, height: 1, background: 'var(--color-ink-100)' }} />
                    or
                    <span style={{ flex: 1, height: 1, background: 'var(--color-ink-100)' }} />
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'center' }}>
                    {GOOGLE_CLIENT_ID && <div ref={googleBtn} />}
                    {APPLE_CLIENT_ID && APPLE_REDIRECT_URI && (
                      <Button type="button" variant="secondary" size="lg" fill onClick={handleApple}>
                        Continue with Apple
                      </Button>
                    )}
                  </div>
                </>
              )}

              <p style={{ fontSize: 12, color: 'var(--color-ink-400)', margin: '18px 0 0', textAlign: 'center' }}>
                Already have an account? <a href="/login" style={{ color: 'var(--color-accent)' }}>Sign in</a>
              </p>
              <p style={{ fontSize: 12, color: 'var(--color-ink-400)', margin: '8px 0 0', textAlign: 'center' }}>
                Just looking? <a href="/preview" style={{ color: 'var(--color-accent)' }}>Explore the live demo</a>
              </p>
              <p style={{ fontSize: 11, color: 'var(--color-ink-300)', margin: '14px 0 0', textAlign: 'center' }}>
                By creating an account you agree to the{' '}
                <a href="/terms" style={{ color: 'var(--color-ink-400)' }}>Terms</a> and{' '}
                <a href="/privacy" style={{ color: 'var(--color-ink-400)' }}>Privacy Policy</a>.
              </p>
            </>
          )}
        </div>
      </Card>
    </div>
  )
}
