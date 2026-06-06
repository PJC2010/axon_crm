'use client'
import { useState, FormEvent } from 'react'
import { useRouter } from 'next/navigation'
import { login } from '@/lib/api'
import { setToken } from '@/lib/auth'

export default function LoginPage() {
  const router = useRouter()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const { access_token } = await login(username, password)
      setToken(access_token)
      router.push('/home')
    } catch {
      setError('Invalid username or password')
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
        background: 'var(--color-paper)',
      }}
    >
      <div
        style={{
          width: 360,
          padding: '40px 36px',
          background: 'var(--color-surface)',
          border: '1px solid var(--color-ink-200)',
          borderRadius: 'var(--radius-card)',
          boxShadow: '0 4px 24px rgba(0,0,0,0.06)',
        }}
      >
        {/* Logo */}
        <div className="flex items-center gap-3 mb-8">
          <svg width="28" height="28" viewBox="0 0 32 32" fill="none" aria-hidden="true">
            <mask id="axon-mark-login">
              <rect width="32" height="32" fill="white" />
              <rect x="2" y="14.5" width="28" height="3" rx="1.5" fill="black" />
              <rect x="14.5" y="2" width="3" height="28" rx="1.5" fill="black" />
            </mask>
            <polygon points="16,5 27,16 16,27 5,16" fill="var(--color-accent)" mask="url(#axon-mark-login)" />
            <circle cx="16" cy="16" r="1.5" fill="var(--color-ink-900)" />
          </svg>
          <span style={{ fontFamily: 'var(--font-display)', fontSize: 22, fontWeight: 600, color: 'var(--color-ink-900)' }}>
            Axon
          </span>
        </div>

        <h1 style={{ fontSize: 18, fontWeight: 600, color: 'var(--color-ink-900)', marginBottom: 24 }}>
          Sign in to your workspace
        </h1>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            <label className="t-label">Username</label>
            <input
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              required
              autoFocus
              className="drawer-input"
              style={{ width: '100%' }}
              placeholder="admin"
            />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            <label className="t-label">Password</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              className="drawer-input"
              style={{ width: '100%' }}
            />
          </div>

          {error && (
            <p style={{ fontSize: 13, color: 'var(--color-danger)', margin: 0 }}>{error}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            style={{
              marginTop: 8,
              padding: '10px 0',
              background: 'var(--color-ink-900)',
              color: 'var(--color-paper)',
              border: 'none',
              borderRadius: 'var(--radius-pill)',
              fontSize: 14,
              fontWeight: 500,
              cursor: loading ? 'not-allowed' : 'pointer',
              opacity: loading ? 0.7 : 1,
            }}
          >
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
