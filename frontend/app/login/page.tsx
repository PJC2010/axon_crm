'use client'
import { useState, useEffect, useRef, FormEvent } from 'react'
import { useRouter } from 'next/navigation'
import { login, loginWithGoogle, loginWithApple } from '@/lib/api'
import { setToken } from '@/lib/auth'
import { Logo, Card, Button, Input } from '@/components/ds'

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_OAUTH_CLIENT_ID
const APPLE_CLIENT_ID = process.env.NEXT_PUBLIC_APPLE_CLIENT_ID
const APPLE_REDIRECT_URI = process.env.NEXT_PUBLIC_APPLE_REDIRECT_URI

// Pull the human-readable reason out of an error thrown by lib/api's req(),
// whose message looks like: API 403: {"detail":"..."}. Falls back to a generic
// line when there's nothing useful to show.
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

// Inject a third-party <script> once and resolve when it has loaded.
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

export default function LoginPage() {
  const router = useRouter()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const googleBtn = useRef<HTMLDivElement>(null)

  function onTokenSuccess(access_token: string) {
    setToken(access_token)
    router.push('/home')
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const { access_token } = await login(username, password)
      onTokenSuccess(access_token)
    } catch {
      setError('Invalid username or password')
    } finally {
      setLoading(false)
    }
  }

  // Google Identity Services: render the official button and exchange the
  // returned ID token (credential) for an Axon JWT.
  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return
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
              setError(reason(err, 'Google sign-in failed'))
            }
          },
        })
        g.accounts.id.renderButton(googleBtn.current, {
          theme: 'outline',
          size: 'large',
          width: 316,
          text: 'continue_with',
        })
      })
      .catch(() => setError('Could not load Google sign-in'))
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Sign in with Apple: init the SDK once; the button click triggers the popup.
  useEffect(() => {
    if (!APPLE_CLIENT_ID || !APPLE_REDIRECT_URI) return
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
      .catch(() => setError('Could not load Apple sign-in'))
  }, [])

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
      // The user closing the Apple popup throws too — keep that quiet-ish.
      setError(reason(err, 'Apple sign-in was cancelled or failed'))
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
      <Card elevation={2} padding={0} style={{ width: '100%', maxWidth: 380 }}>
        <div style={{ padding: '36px 32px' }}>
          <div style={{ marginBottom: 26 }}>
            <Logo size={26} />
          </div>

          <h1 className="t-title" style={{ fontSize: 18, margin: '0 0 22px' }}>
            Sign in to your workspace
          </h1>

          <form onSubmit={handleSubmit}>
            <div style={{ marginBottom: 14 }}>
              <Input
                label="Username or email"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="you@company.com"
                autoFocus
                required
                fill
              />
            </div>
            <div style={{ marginBottom: 6 }}>
              <Input
                label="Password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                fill
              />
            </div>
            <p style={{ margin: `0 0 ${error ? 14 : 22}px`, textAlign: 'right' }}>
              <a href="/reset-password" style={{ fontSize: 12, color: 'var(--color-ink-400)' }}>
                Forgot password?
              </a>
            </p>

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
              {loading ? 'Signing in…' : 'Sign in'}
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
            New to Axon? <a href="/signup" style={{ color: 'var(--color-accent)' }}>Start free</a>
          </p>
          <p style={{ fontSize: 12, color: 'var(--color-ink-400)', margin: '8px 0 0', textAlign: 'center' }}>
            Just looking? <a href="/preview" style={{ color: 'var(--color-accent)' }}>Explore the live demo</a>
          </p>
        </div>
      </Card>
    </div>
  )
}
