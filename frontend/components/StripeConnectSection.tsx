'use client'
import { Skeleton } from './ds'
import { useCallback, useEffect, useState } from 'react'
import { CreditCard, CheckCircle2, AlertCircle } from 'lucide-react'
import { getStripeStatus, connectStripe } from '@/lib/api'
import type { StripeStatus } from '@/lib/types'

/** Settings card for online payments: connect a Stripe Express account, resume
 *  unfinished onboarding, or show the ready state. Returning from Stripe lands
 *  back on /settings (?stripe=return|refresh), which re-mounts and re-fetches —
 *  and account.updated webhooks keep the stored flags fresh regardless. */
export function StripeConnectSection() {
  const [status, setStatus] = useState<StripeStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setStatus(await getStripeStatus())
    } catch {
      // Non-owners and transient failures: leave the card in its muted state.
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  async function handleConnect() {
    setBusy(true)
    setError(null)
    try {
      const { url } = await connectStripe()
      window.location.href = url
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not start Stripe onboarding')
      setBusy(false)
    }
  }

  const ready = status?.connected && status.charges_enabled
  const inProgress = status?.connected && !status.charges_enabled

  return (
    <section>
      <h2 className="t-eyebrow" style={{ marginBottom: 6 }}>Payments</h2>
      <p style={{ fontSize: 13, color: 'var(--color-ink-400)', margin: '0 0 12px' }}>
        Let customers pay invoices online by card. Payments go straight to your own
        Stripe account, and invoice emails and texts automatically include a pay link.
      </p>

      <div style={{
        display: 'flex', alignItems: 'center', gap: 12, padding: '14px 16px',
        background: 'var(--color-surface)', border: '1px solid var(--color-ink-200)',
        borderRadius: 'var(--radius-card)',
      }}>
        <CreditCard size={18} strokeWidth={1.5} style={{ color: 'var(--color-ink-500)', flexShrink: 0 }} />

        {loading ? (
          <Skeleton h={13} w={200} />
        ) : !status?.available ? (
          <span style={{ fontSize: 13, color: 'var(--color-ink-400)' }}>
            Online payments aren&apos;t enabled on this server.
          </span>
        ) : ready ? (
          <>
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 600, color: 'var(--color-moss)' }}>
                <CheckCircle2 size={14} strokeWidth={2} /> Stripe connected — accepting payments
              </div>
              <p style={{ fontSize: 12, color: 'var(--color-ink-400)', margin: '2px 0 0' }}>
                {status.payouts_enabled
                  ? 'Payouts are enabled.'
                  : 'Payouts are not enabled yet — check your Stripe dashboard.'}
              </p>
            </div>
          </>
        ) : inProgress ? (
          <>
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 600, color: 'var(--color-warning, #B45309)' }}>
                <AlertCircle size={14} strokeWidth={2} /> Onboarding not finished
              </div>
              <p style={{ fontSize: 12, color: 'var(--color-ink-400)', margin: '2px 0 0' }}>
                Stripe needs a few more details before you can accept payments.
              </p>
            </div>
            <button onClick={handleConnect} disabled={busy} className="btn-primary">
              {busy ? 'Opening…' : 'Finish setup'}
            </button>
          </>
        ) : (
          <>
            <span style={{ flex: 1, fontSize: 13, color: 'var(--color-ink-600)' }}>
              Not connected yet.
            </span>
            <button onClick={handleConnect} disabled={busy} className="btn-primary">
              {busy ? 'Opening…' : 'Connect Stripe'}
            </button>
          </>
        )}
      </div>

      {error && <p style={{ fontSize: 12, color: 'var(--color-rose)', marginTop: 8 }}>{error}</p>}
    </section>
  )
}
