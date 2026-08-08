'use client'
import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, Home, Phone, PhoneMissed, PhoneIncoming, Settings } from 'lucide-react'
import { getCalls, getCallSettings } from '@/lib/api'
import { AuthGuard } from '@/components/AuthGuard'
import { ModuleGate } from '@/components/ModuleGate'
import type { CallLogEntry, CallOutcome, CallSettings } from '@/lib/types'

const PAGE_SIZE = 50

const OUTCOME_LABEL: Record<CallOutcome, string> = {
  answered: 'Answered',
  missed: 'Missed',
  busy: 'Busy',
}
const OUTCOME_COLOR: Record<CallOutcome, string> = {
  answered: 'var(--color-moss)',
  missed: 'var(--color-danger)',
  busy: 'var(--color-warning, #B45309)',
}

function fmtWhen(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  })
}

function fmtDuration(seconds: number | null): string {
  if (seconds == null) return '—'
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return m ? `${m}m ${s}s` : `${s}s`
}

function CallsPage() {
  const [items, setItems] = useState<CallLogEntry[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [outcome, setOutcome] = useState<CallOutcome | ''>('')
  const [settings, setSettings] = useState<CallSettings | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async (nextOffset: number, nextOutcome: CallOutcome | '') => {
    setLoading(true)
    try {
      const [page, s] = await Promise.all([
        getCalls({ limit: PAGE_SIZE, offset: nextOffset, ...(nextOutcome ? { outcome: nextOutcome } : {}) }),
        getCallSettings(),
      ])
      setItems(page.items)
      setTotal(page.total)
      setSettings(s)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load(offset, outcome) }, [load, offset, outcome])

  const noNumberYet = settings !== null && !settings.number

  return (
    <div style={{ minHeight: '100vh', background: 'transparent' }}>
      <header style={{
        height: 64, padding: '0 28px', display: 'flex', alignItems: 'center', gap: 16,
        borderBottom: '1px solid var(--color-ink-200)', background: 'var(--color-paper)',
      }}>
        <Link href="/dashboard" className="dash-icon-btn" style={{ textDecoration: 'none', color: 'inherit' }}>
          <ArrowLeft size={15} strokeWidth={1.5} />
        </Link>
        <Link href="/home" title="Home" className="dash-icon-btn" style={{ textDecoration: 'none', color: 'inherit' }}>
          <Home size={15} strokeWidth={1.5} />
        </Link>
        <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 600, color: 'var(--color-ink-900)', margin: 0 }}>
          Calls
        </h1>
        {settings?.number && (
          <span style={{ fontSize: 12, color: 'var(--color-ink-400)' }}>
            Tracking number: {settings.number.friendly_name || settings.number.phone_number}
          </span>
        )}
      </header>

      <div style={{ maxWidth: 860, margin: '0 auto', padding: '28px 20px' }}>
        {/* Outcome filter */}
        <div style={{ display: 'flex', gap: 6, marginBottom: 16 }}>
          {(['', 'answered', 'missed', 'busy'] as const).map(o => (
            <button
              key={o || 'all'}
              onClick={() => { setOffset(0); setOutcome(o) }}
              style={{
                padding: '6px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
                borderRadius: 'var(--radius-button)',
                border: '1px solid var(--color-ink-200)',
                background: outcome === o ? 'var(--color-accent)' : 'var(--color-surface)',
                color: 'var(--color-ink-900)',
              }}
            >
              {o ? OUTCOME_LABEL[o] : 'All'}
            </button>
          ))}
        </div>

        {loading ? (
          <p style={{ color: 'var(--color-ink-400)', fontSize: 13 }}>Loading…</p>
        ) : noNumberYet ? (
          <div style={{
            padding: '32px 24px', textAlign: 'center',
            background: 'var(--color-surface)', border: '1px solid var(--color-ink-200)',
            borderRadius: 'var(--radius-card)',
          }}>
            <Phone size={22} strokeWidth={1.5} style={{ color: 'var(--color-ink-400)', marginBottom: 10 }} />
            <p style={{ fontSize: 14, color: 'var(--color-ink-600)', margin: '0 0 14px' }}>
              No tracking number yet. Enter the phone your business line already rings on and
              we&apos;ll assign you a local number that forwards to it — every call lands here,
              unknown callers become leads, and missed callers get a text back automatically.
            </p>
            <Link
              href="/settings?tab=integrations"
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 6,
                padding: '10px 16px', borderRadius: 'var(--radius-button)',
                background: 'var(--color-accent)', color: 'var(--color-ink-900)',
                textDecoration: 'none', fontSize: 14, fontWeight: 600,
              }}
            >
              <Settings size={14} strokeWidth={2} /> Set up call tracking
            </Link>
          </div>
        ) : items.length === 0 ? (
          <p style={{ fontSize: 13, color: 'var(--color-ink-400)' }}>
            No calls {outcome ? `with outcome “${OUTCOME_LABEL[outcome]}”` : ''} yet.
          </p>
        ) : (
          <>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--color-ink-200)' }}>
                  {['', 'Caller', 'Outcome', 'Duration', 'When'].map((h, i) => (
                    <th key={i} style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--color-ink-400)', fontWeight: 500, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.map(c => (
                  <tr key={c.id} style={{ borderBottom: '1px solid var(--color-ink-100, rgba(0,0,0,0.04))' }}>
                    <td style={{ padding: '8px', width: 24 }}>
                      {c.outcome === 'answered'
                        ? <PhoneIncoming size={14} strokeWidth={1.5} style={{ color: OUTCOME_COLOR.answered }} />
                        : <PhoneMissed size={14} strokeWidth={1.5} style={{ color: c.outcome ? OUTCOME_COLOR[c.outcome] : 'var(--color-ink-400)' }} />}
                    </td>
                    <td style={{ padding: '8px' }}>
                      {c.property_id ? (
                        <Link href={`/leads/${c.property_id}`} style={{ color: 'var(--color-ink-900)', fontWeight: 600, textDecoration: 'none' }}>
                          {c.contact_name || c.caller_name || c.from_number || 'Unknown'}
                        </Link>
                      ) : (
                        <span>{c.caller_name || c.from_number || 'Unknown'}</span>
                      )}
                      {c.lead_created && (
                        <span style={{
                          marginLeft: 8, fontSize: 10, fontWeight: 600, textTransform: 'uppercase',
                          letterSpacing: '0.04em', color: 'var(--color-moss)',
                        }}>
                          New lead
                        </span>
                      )}
                    </td>
                    <td style={{ padding: '8px' }}>
                      {c.outcome ? (
                        <span style={{ fontWeight: 600, color: OUTCOME_COLOR[c.outcome] }}>{OUTCOME_LABEL[c.outcome]}</span>
                      ) : (
                        <span style={{ color: 'var(--color-ink-400)' }}>In progress</span>
                      )}
                    </td>
                    <td style={{ padding: '8px', color: 'var(--color-ink-600)' }}>{fmtDuration(c.duration_seconds)}</td>
                    <td style={{ padding: '8px', color: 'var(--color-ink-400)' }}>{fmtWhen(c.started_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            {total > PAGE_SIZE && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 16, fontSize: 13 }}>
                <button
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                  disabled={offset === 0}
                  className="dash-icon-btn"
                >
                  Previous
                </button>
                <span style={{ color: 'var(--color-ink-400)' }}>
                  {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
                </span>
                <button
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                  disabled={offset + PAGE_SIZE >= total}
                  className="dash-icon-btn"
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

export default function CallsPageGuarded() {
  return (
    <AuthGuard>
      <ModuleGate module="calls" feature="Call tracking">
        <CallsPage />
      </ModuleGate>
    </AuthGuard>
  )
}
