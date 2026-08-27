'use client'
import { use, useEffect, useRef, useState } from 'react'
import { CheckCircle2, FileText, Receipt } from 'lucide-react'
import { getPublicPayInfo, createPublicCheckout } from '@/lib/api'
import type { PublicPayInfo } from '@/lib/types'

function fmt(n: number) { return n.toLocaleString('en-US', { style: 'currency', currency: 'USD' }) }
function fmtDate(s: string) {
  const [y, m, d] = s.split('-')
  return `${['January','February','March','April','May','June','July','August','September','October','November','December'][parseInt(m)-1]} ${parseInt(d)}, ${y}`
}

/** Customer-facing pay page, linked from invoice emails/texts. After Stripe
 *  Checkout redirects back with ?status=success the webhook may still be in
 *  flight, so we poll until the invoice flips to paid (capped at ~2 minutes). */
export default function PublicPayPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params)
  const [info, setInfo] = useState<PublicPayInfo | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [awaitingConfirmation, setAwaitingConfirmation] = useState(false)
  const pollCount = useRef(0)

  useEffect(() => {
    let cancelled = false
    getPublicPayInfo(token)
      .then(i => { if (!cancelled) setInfo(i) })
      .catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : 'Invoice not found') })
    return () => { cancelled = true }
  }, [token])

  // Back from Stripe Checkout: poll for the webhook to land.
  useEffect(() => {
    if (typeof window === 'undefined') return
    if (new URLSearchParams(window.location.search).get('status') !== 'success') return
    setAwaitingConfirmation(true)
  }, [])

  useEffect(() => {
    if (!awaitingConfirmation || info?.status === 'paid') return
    if (pollCount.current >= 40) { setAwaitingConfirmation(false); return }
    const t = setTimeout(() => {
      pollCount.current += 1
      getPublicPayInfo(token).then(setInfo).catch(() => {})
    }, 3000)
    return () => clearTimeout(t)
  }, [awaitingConfirmation, info, token])

  async function handlePay() {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      const { url } = await createPublicCheckout(token)
      window.location.href = url
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start the payment')
      setBusy(false)
    }
  }

  if (error && !info) {
    return (
      <div style={{ minHeight: '100dvh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'transparent', padding: 20 }}>
        <div style={{ textAlign: 'center', maxWidth: 360 }}>
          <Receipt size={36} strokeWidth={1.2} color="var(--color-ink-300)" style={{ marginBottom: 12 }} />
          <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 600, color: 'var(--color-ink-900)', marginBottom: 8 }}>Invoice unavailable</h1>
          <p style={{ fontSize: 14, color: 'var(--color-ink-500)', lineHeight: 1.5 }}>{error}</p>
        </div>
      </div>
    )
  }

  if (!info) {
    return (
      <div style={{ minHeight: '100dvh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'transparent' }}>
        <span style={{ fontSize: 14, color: 'var(--color-ink-400)' }}>Loading invoice…</span>
      </div>
    )
  }

  const paid = info.status === 'paid'
  const voided = info.status === 'void'
  const confirming = awaitingConfirmation && !paid

  return (
    <div style={{ minHeight: '100dvh', background: 'var(--color-ink-50)', padding: '24px 16px 60px' }}>
      <div style={{ maxWidth: 480, margin: '0 auto' }}>

        {paid && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 18px', marginBottom: 16, borderRadius: 'var(--radius-card)', background: 'rgba(60,120,80,0.12)', color: 'var(--color-moss)', fontWeight: 600, fontSize: 14 }}>
            <CheckCircle2 size={18} strokeWidth={2} />
            Paid in full — thank you!
          </div>
        )}
        {confirming && (
          <div style={{ padding: '14px 18px', marginBottom: 16, borderRadius: 'var(--radius-card)', background: 'var(--color-ink-100)', color: 'var(--color-ink-600)', fontWeight: 600, fontSize: 14 }}>
            Payment received — confirming with the bank…
          </div>
        )}
        {voided && (
          <div style={{ padding: '14px 18px', marginBottom: 16, borderRadius: 'var(--radius-card)', background: 'var(--color-ink-100)', color: 'var(--color-ink-600)', fontWeight: 600, fontSize: 14 }}>
            This invoice has been voided. Contact {info.business_name} with any questions.
          </div>
        )}

        <div style={{ background: 'white', borderRadius: 'var(--radius-card)', border: '1px solid var(--color-ink-200)', boxShadow: 'var(--shadow-card)', overflow: 'hidden' }}>
          <div style={{ padding: '24px 24px 20px', borderBottom: '1px solid var(--color-ink-200)' }}>
            <p className="t-eyebrow" style={{ marginBottom: 4 }}>{info.business_name}</p>
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
              <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 22, fontWeight: 600, color: 'var(--color-ink-900)', margin: 0 }}>
                Invoice {info.invoice_number}
              </h1>
              <span className="tabular" style={{ fontSize: 22, fontWeight: 700, color: 'var(--color-ink-900)' }}>{fmt(info.total)}</span>
            </div>
            <p style={{ fontSize: 13, color: 'var(--color-ink-500)', margin: '8px 0 0' }}>
              Issued {fmtDate(info.issue_date)}
              {info.due_date ? ` · Due ${fmtDate(info.due_date)}` : ''}
            </p>
          </div>

          <div style={{ padding: '14px 24px 20px', background: 'var(--color-ink-50)' }}>
            {info.amount_paid > 0 && (
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, color: 'var(--color-ink-600)', marginBottom: 4 }}>
                <span>Paid so far</span><span className="tabular">{fmt(info.amount_paid)}</span>
              </div>
            )}
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 16, fontWeight: 700, color: 'var(--color-ink-900)', marginTop: 6 }}>
              <span>Balance due</span><span className="tabular">{fmt(info.balance_due)}</span>
            </div>
          </div>

          <div style={{ padding: '12px 24px', borderTop: '1px solid var(--color-ink-200)' }}>
            <a href={info.pdf_url} target="_blank" rel="noopener noreferrer"
               style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: 'var(--color-accent-300)', textDecoration: 'none', fontWeight: 500 }}>
              <FileText size={14} strokeWidth={1.5} /> View invoice PDF
            </a>
          </div>
        </div>

        {info.payable && !paid && !confirming && (
          <button onClick={handlePay} disabled={busy} className="btn-primary" style={{ width: '100%', height: 52, fontSize: 15, fontWeight: 600, marginTop: 20 }}>
            {busy ? 'Opening secure checkout…' : `Pay ${fmt(info.balance_due)}`}
          </button>
        )}
        {!info.payable && !paid && !voided && (
          <p style={{ marginTop: 16, fontSize: 13, color: 'var(--color-ink-500)', textAlign: 'center' }}>
            Online payment isn&apos;t available for this invoice — contact {info.business_name} to arrange payment.
          </p>
        )}

        {error && info && (
          <p style={{ marginTop: 14, fontSize: 13, color: 'var(--color-rose)', textAlign: 'center' }}>{error}</p>
        )}

        <p style={{ textAlign: 'center', fontSize: 12, color: 'var(--color-ink-400)', marginTop: 28 }}>
          Payments are processed securely by Stripe.
        </p>
      </div>
    </div>
  )
}
