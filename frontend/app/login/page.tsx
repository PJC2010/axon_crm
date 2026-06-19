'use client'
import { useState, FormEvent } from 'react'
import { useRouter } from 'next/navigation'
import { Button, Callout, Card, Elevation, FormGroup, InputGroup } from '@blueprintjs/core'
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
        background: 'transparent',
        padding: 20,
      }}
    >
      <Card elevation={Elevation.TWO} style={{ width: 360, padding: '36px 32px' }}>
        {/* Logo */}
        <div className="flex items-center gap-3" style={{ marginBottom: 28 }}>
          <svg width="28" height="28" viewBox="0 0 32 32" fill="none" aria-hidden="true">
            <mask id="axon-mark-login">
              <rect width="32" height="32" fill="white" />
              <rect x="2" y="14.5" width="28" height="3" rx="1.5" fill="black" />
              <rect x="14.5" y="2" width="3" height="28" rx="1.5" fill="black" />
            </mask>
            <polygon points="16,5 27,16 16,27 5,16" fill="var(--color-accent)" mask="url(#axon-mark-login)" />
            <circle cx="16" cy="16" r="1.5" fill="var(--color-ink-900)" />
          </svg>
          <span style={{ fontFamily: 'var(--font-display)', fontSize: 22, fontWeight: 600, color: '#fff' }}>
            Axon
          </span>
        </div>

        <h1 style={{ fontSize: 18, fontWeight: 600, color: 'var(--color-ink-900)', marginBottom: 24 }}>
          Sign in to your workspace
        </h1>

        <form onSubmit={handleSubmit}>
          <FormGroup label="Username" labelFor="login-username">
            <InputGroup
              id="login-username"
              type="text"
              value={username}
              onValueChange={setUsername}
              required
              autoFocus
              fill
              placeholder="admin"
            />
          </FormGroup>

          <FormGroup label="Password" labelFor="login-password">
            <InputGroup
              id="login-password"
              type="password"
              value={password}
              onValueChange={setPassword}
              required
              fill
            />
          </FormGroup>

          {error && (
            <Callout intent="danger" style={{ marginBottom: 14 }}>
              {error}
            </Callout>
          )}

          <Button
            type="submit"
            intent="primary"
            fill
            large
            loading={loading}
            text="Sign in"
          />
        </form>
      </Card>
    </div>
  )
}
