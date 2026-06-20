'use client'
import { useState, FormEvent } from 'react'
import { useRouter } from 'next/navigation'
import { login } from '@/lib/api'
import { setToken } from '@/lib/auth'
import { Logo, Card, Button, Input } from '@/components/ds'

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
                label="Username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="admin"
                autoFocus
                required
                fill
              />
            </div>
            <div style={{ marginBottom: error ? 14 : 22 }}>
              <Input
                label="Password"
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
              {loading ? 'Signing in…' : 'Sign in'}
            </Button>
          </form>

          <p style={{ fontSize: 12, color: 'var(--color-ink-400)', margin: '18px 0 0', textAlign: 'center' }}>
            Built on data, powered by people.
          </p>
        </div>
      </Card>
    </div>
  )
}
