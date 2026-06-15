'use client'
import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { Plug, Upload, Trash2, ThumbsUp, Camera, ArrowRight } from 'lucide-react'
import { getConnections, createConnection, deleteConnection } from '@/lib/api'
import type { Connection } from '@/lib/types'
import { ConnectMetaModal } from './ConnectMetaModal'

// Providers a user can connect today (file-upload import). OAuth comes later.
const PROVIDERS: { id: string; label: string; icon: typeof ThumbsUp }[] = [
  { id: 'meta_facebook', label: 'Facebook', icon: ThumbsUp },
  { id: 'meta_instagram', label: 'Instagram', icon: Camera },
]

function fmtSynced(ts: string | null): string {
  if (!ts) return 'No data yet'
  const d = new Date(ts)
  return `Synced ${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`
}

export function ConnectionsSection() {
  const [connections, setConnections] = useState<Connection[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [uploadFor, setUploadFor] = useState<Connection | null>(null)

  const load = useCallback(async () => {
    try {
      setConnections(await getConnections())
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const byProvider = (id: string) => connections.find(c => c.provider === id)

  async function handleConnect(provider: string) {
    setBusy(provider)
    try {
      const conn = await createConnection({ provider })
      await load()
      setUploadFor(conn)            // jump straight to uploading an export
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Could not connect')
    } finally {
      setBusy(null)
    }
  }

  async function handleDisconnect(conn: Connection) {
    if (!confirm(`Disconnect ${conn.display_name || conn.provider}? This removes its imported data.`)) return
    await deleteConnection(conn.id)
    setConnections(prev => prev.filter(c => c.id !== conn.id))
  }

  return (
    <section>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Plug size={14} strokeWidth={1.5} style={{ color: 'var(--color-accent)' }} />
          <h2 className="t-eyebrow" style={{ margin: 0 }}>Connected accounts</h2>
        </div>
        <Link
          href="/marketing"
          style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 500, color: 'var(--color-accent)', textDecoration: 'none' }}
        >
          Marketing insights <ArrowRight size={12} strokeWidth={1.8} />
        </Link>
      </div>

      <p style={{ margin: '0 0 14px', fontSize: 13, color: 'var(--color-ink-500)', lineHeight: 1.5 }}>
        Connect your social accounts and upload their exports so Axon can analyze your
        digital presence and suggest ways to win more customers.
      </p>

      {/* Connect buttons for providers not yet connected */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: connections.length ? 16 : 0 }}>
        {PROVIDERS.filter(p => !byProvider(p.id)).map(p => {
          const Icon = p.icon
          return (
            <button
              key={p.id}
              onClick={() => handleConnect(p.id)}
              disabled={busy === p.id}
              className="btn-secondary"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, padding: '6px 12px' }}
            >
              <Icon size={14} strokeWidth={1.6} />
              {busy === p.id ? 'Connecting…' : `Connect ${p.label}`}
            </button>
          )
        })}
      </div>

      {loading ? (
        <p style={{ fontSize: 13, color: 'var(--color-ink-400)' }}>Loading…</p>
      ) : connections.length > 0 ? (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--color-ink-200)' }}>
              {['Account', 'Status', 'Last sync', ''].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--color-ink-400)', fontWeight: 500, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {connections.map(c => (
              <tr key={c.id} style={{ borderBottom: '1px solid var(--color-ink-100)' }}>
                <td style={{ padding: '8px', fontWeight: 500 }}>{c.display_name || c.provider}</td>
                <td style={{ padding: '8px' }}>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, color: c.status === 'connected' ? 'var(--color-moss)' : 'var(--color-ink-400)' }}>
                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: c.status === 'connected' ? 'var(--color-moss)' : 'var(--color-ink-300)' }} />
                    {c.status}
                  </span>
                </td>
                <td style={{ padding: '8px', color: 'var(--color-ink-500)' }}>{fmtSynced(c.last_synced_at)}</td>
                <td style={{ padding: '8px' }}>
                  <div style={{ display: 'flex', gap: 4, justifyContent: 'flex-end' }}>
                    <button
                      onClick={() => setUploadFor(c)}
                      className="dash-icon-btn"
                      title="Upload export"
                      style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}
                    >
                      <Upload size={13} strokeWidth={1.6} /> Upload
                    </button>
                    <button onClick={() => handleDisconnect(c)} className="dash-icon-btn" title="Disconnect" style={{ padding: 4, color: 'var(--color-danger)' }}>
                      <Trash2 size={12} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      {uploadFor && (
        <ConnectMetaModal
          connection={uploadFor}
          onClose={() => setUploadFor(null)}
          onImported={load}
        />
      )}
    </section>
  )
}
