'use client'
import { use, useEffect, useState } from 'react'
import { CheckCircle2, XCircle, FileText } from 'lucide-react'
import { getPublicQuote, acceptPublicQuote, declinePublicQuote } from '@/lib/api'
import type { PublicQuote } from '@/lib/types'

function fmt(n: number) { return n.toLocaleString('en-US', { style: 'currency', currency: 'USD' }) }
function fmtDate(s: string) {
  const [y, m, d] = s.split('-')
  return `${['January','February','March','April','May','June','July','August','September','October','November','December'][parseInt(m)-1]} ${parseInt(d)}, ${y}`
}

export default function PublicQuotePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params)
  const [quote, setQuote] = useState<PublicQuote | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [declining, setDeclining] = useState(false)
  const [reason, setReason] = useState('')

  useEffect(() => {
    let cancelled = false
    getPublicQuote(token)
      .then(q => { if (!cancelled) setQuote(q) })
      .catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : 'Quote not found') })
    return () => { cancelled = true }
  }, [token])

  async function handleAccept() {
    if (busy || !confirm('Accept this quote? The business will be notified and will follow up to schedule the work.')) return
    setBusy(true)
    try {
      setQuote(await acceptPublicQuote(token))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong')
    } finally { setBusy(false) }
  }

  async function handleDecline() {
    if (busy) return
    setBusy(true)
    try {
      setQuote(await declinePublicQuote(token, reason.trim() || undefined))
      setDeclining(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong')
    } finally { setBusy(false) }
  }

  if (error && !quote) {
    return (
      <div style={{ minHeight: '100dvh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'transparent', padding: 20 }}>
        <div style={{ textAlign: 'center', maxWidth: 360 }}>
          <FileText size={36} strokeWidth={1.2} color="var(--color-ink-300)" style={{ marginBottom: 12 }} />
          <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 600, color: 'var(--color-ink-900)', marginBottom: 8 }}>Quote unavailable</h1>
          <p style={{ fontSize: 14, color: 'var(--color-ink-500)', lineHeight: 1.5 }}>{error}</p>
        </div>
      </div>
    )
  }

  if (!quote) {
    return (
      <div style={{ minHeight: '100dvh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'transparent' }}>
        <span style={{ fontSize: 14, color: 'var(--color-ink-400)' }}>Loading quote…</span>
      </div>
    )
  }

  const open = quote.status === 'sent' || quote.status === 'draft'

  return (
    <div style={{ minHeight: '100dvh', background: 'var(--color-ink-50)', padding: '24px 16px 60px' }}>
      <div style={{ maxWidth: 560, margin: '0 auto' }}>

        {/* Status banner */}
        {quote.status === 'accepted' && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 18px', marginBottom: 16, borderRadius: 'var(--radius-card)', background: 'rgba(60,120,80,0.12)', color: 'var(--color-moss)', fontWeight: 600, fontSize: 14 }}>
            <CheckCircle2 size={18} strokeWidth={2} />
            Quote accepted{quote.accepted_at ? ` on ${fmtDate(quote.accepted_at.slice(0, 10))}` : ''} — {quote.business_name} will be in touch to schedule the work.
          </div>
        )}
        {quote.status === 'declined' && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 18px', marginBottom: 16, borderRadius: 'var(--radius-card)', background: 'rgba(180,60,60,0.1)', color: 'var(--color-rose)', fontWeight: 600, fontSize: 14 }}>
            <XCircle size={18} strokeWidth={2} />
            Quote declined. Changed your mind? Contact {quote.business_name} directly.
          </div>
        )}
        {quote.status === 'expired' && (
          <div style={{ padding: '14px 18px', marginBottom: 16, borderRadius: 'var(--radius-card)', background: 'var(--color-ink-100)', color: 'var(--color-ink-600)', fontWeight: 600, fontSize: 14 }}>
            This quote has expired. Contact {quote.business_name} for an updated quote.
          </div>
        )}

        {/* Quote document */}
        <div style={{ background: 'white', borderRadius: 'var(--radius-card)', border: '1px solid var(--color-ink-200)', boxShadow: 'var(--shadow-card)', overflow: 'hidden' }}>
          <div style={{ padding: '24px 24px 20px', borderBottom: '1px solid var(--color-ink-200)' }}>
            <p className="t-eyebrow" style={{ marginBottom: 4 }}>{quote.business_name}</p>
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
              <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 22, fontWeight: 600, color: 'var(--color-ink-900)', margin: 0 }}>
                Quote {quote.quote_number}
              </h1>
              <span className="tabular" style={{ fontSize: 22, fontWeight: 700, color: 'var(--color-ink-900)' }}>{fmt(quote.total)}</span>
            </div>
            <p style={{ fontSize: 13, color: 'var(--color-ink-500)', margin: '8px 0 0' }}>
              Prepared for {quote.client_name} · {fmtDate(quote.issue_date)}
              {quote.valid_until ? ` · Valid until ${fmtDate(quote.valid_until)}` : ''}
            </p>
          </div>

          {/* Line items */}
          <div style={{ padding: '8px 24px' }}>
            {quote.line_items.map((li, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', gap: 16, padding: '12px 0', borderBottom: i < quote.line_items.length - 1 ? '1px solid var(--color-ink-100)' : 'none' }}>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 500, color: 'var(--color-ink-800)' }}>{li.description}</div>
                  {li.quantity !== 1 && (
                    <div style={{ fontSize: 12, color: 'var(--color-ink-400)', marginTop: 2 }}>{li.quantity} × {fmt(li.unit_price)}</div>
                  )}
                </div>
                <span className="tabular" style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-ink-800)', flexShrink: 0 }}>{fmt(li.amount)}</span>
              </div>
            ))}
          </div>

          {/* Totals */}
          <div style={{ padding: '14px 24px 20px', borderTop: '1px solid var(--color-ink-200)', background: 'var(--color-ink-50)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, color: 'var(--color-ink-600)', marginBottom: 4 }}>
              <span>Subtotal</span><span className="tabular">{fmt(quote.subtotal)}</span>
            </div>
            {quote.tax_rate > 0 && (
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, color: 'var(--color-ink-600)', marginBottom: 4 }}>
                <span>Tax ({quote.tax_rate}%)</span><span className="tabular">{fmt(quote.tax_amount)}</span>
              </div>
            )}
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 16, fontWeight: 700, color: 'var(--color-ink-900)', marginTop: 6 }}>
              <span>Total</span><span className="tabular">{fmt(quote.total)}</span>
            </div>
          </div>

          {quote.notes && (
            <div style={{ padding: '14px 24px', borderTop: '1px solid var(--color-ink-200)', fontSize: 13, color: 'var(--color-ink-600)', lineHeight: 1.5 }}>
              {quote.notes}
            </div>
          )}
        </div>

        {/* Actions */}
        {open && !declining && (
          <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
            <button onClick={handleAccept} disabled={busy} className="btn-primary" style={{ flex: 1, height: 52, fontSize: 15, fontWeight: 600 }}>
              {busy ? 'Working…' : 'Accept quote'}
            </button>
            <button onClick={() => setDeclining(true)} disabled={busy} className="btn-secondary" style={{ flex: '0 0 130px', height: 52, fontSize: 14 }}>
              Decline
            </button>
          </div>
        )}
        {open && declining && (
          <div style={{ marginTop: 20, background: 'white', borderRadius: 'var(--radius-card)', border: '1px solid var(--color-ink-200)', padding: 16 }}>
            <label style={{ display: 'block', fontSize: 13, fontWeight: 600, color: 'var(--color-ink-700)', marginBottom: 8 }}>
              Mind telling us why? (optional)
            </label>
            <textarea
              value={reason}
              onChange={e => setReason(e.target.value)}
              placeholder="e.g. went with another company, price, timing…"
              rows={3}
              style={{ width: '100%', boxSizing: 'border-box', padding: '10px 12px', fontSize: 14, border: '1px solid var(--color-ink-200)', borderRadius: 'var(--radius-input)', resize: 'vertical', fontFamily: 'inherit' }}
            />
            <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
              <button onClick={handleDecline} disabled={busy} className="btn-primary" style={{ flex: 1, height: 44, fontSize: 14, background: 'var(--color-rose)' }}>
                {busy ? 'Working…' : 'Confirm decline'}
              </button>
              <button onClick={() => setDeclining(false)} disabled={busy} className="btn-secondary" style={{ flex: '0 0 100px', height: 44, fontSize: 14 }}>
                Back
              </button>
            </div>
          </div>
        )}

        {error && quote && (
          <p style={{ marginTop: 14, fontSize: 13, color: 'var(--color-rose)', textAlign: 'center' }}>{error}</p>
        )}

        <p style={{ textAlign: 'center', fontSize: 12, color: 'var(--color-ink-400)', marginTop: 28 }}>
          Questions? Reply to the message that sent you this quote.
        </p>
      </div>
    </div>
  )
}
