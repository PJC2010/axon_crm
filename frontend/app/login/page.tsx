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
          <svg width="28" height="28" viewBox="0 0 40 40" fill="none">
            <path
              d="M4 32 C 12 32, 14 22, 22 22 C 30 22, 30 14, 38 6"
              stroke="var(--color-ink-900)" strokeWidth="2.5"
              strokeLinecap="round" strokeLinejoin="round"
            />
            <circle cx="4" cy="32" r="3" fill="var(--color-ink-900)" />
            <circle cx="22" cy="22" r="4" fill="var(--color-paper)" stroke="var(--color-ink-900)" strokeWidth="2.5" />
            <circle cx="38" cy="6" r="6" fill="var(--color-accent)" />
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
