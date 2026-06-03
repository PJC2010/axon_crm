'use client'
import { useEffect, useState, useCallback, Suspense } from 'react'
import { useParams, useSearchParams } from 'next/navigation'
import { CreditCard, CheckCircle2, Loader2 } from 'lucide-react'
import { getPublicInvoice, startPublicCheckout } from '@/lib/api'
import type { PublicInvoiceView } from '@/lib/types'

const MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
function fmt(n: number) { return n.toLocaleString('en-US', { style: 'currency', currency: 'USD' }) }
function fmtDate(s: string) {
  const [y, m, d] = s.split('-')
  return `${MONTH_NAMES[parseInt(m)-1]} ${parseInt(d)}, ${y}`
}

// Public, unauthenticated invoice pay page. NOT wrapped in AuthGuard.
// useSearchParams requires a Suspense boundary in the App Router.
export default function PayPage() {
  return (
    <Suspense fallback={<Centered><Loader2 size={20} className="spin" /></Centered>}>
      <PayPageInner />
    </Suspense>
  )
}

function PayPageInner() {
  const params = useParams<{ token: string }>()
  const token = params.token
  const search = useSearchParams()
  const justPaid = search.get('paid') === '1'

  const [invoice, setInvoice] = useState<PublicInvoiceView | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [paying, setPaying] = useState(false)
  // After returning from Stripe we poll until the webhook flips status to paid.
  const [awaitingPayment, setAwaitingPayment] = useState(justPaid)

  const load = useCallback(async () => {
    try {
      const inv = await getPublicInvoice(token)
      setInvoice(inv)
      if (inv.status === 'paid' || inv.balance_due <= 0) setAwaitingPayment(false)
      return inv
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Invoice not found')
      return null
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => { void (async () => { await load() })() }, [load])

  // Poll for ~30s after returning from Stripe while the webhook settles.
  useEffect(() => {
    if (!awaitingPayment) return
    let tries = 0
    const id = setInterval(async () => {
      tries += 1
      const inv = await load()
      if ((inv && (inv.status === 'paid' || inv.balance_due <= 0)) || tries >= 15) {
        clearInterval(id)
        setAwaitingPayment(false)
      }
    }, 2000)
    return () => clearInterval(id)
  }, [awaitingPayment, load])

  async function handlePay() {
    setPaying(true); setError(null)
    try {
      const { url } = await startPublicCheckout(token)
      window.location.href = url
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not start payment')
      setPaying(false)
    }
  }

  if (loading) {
    return <Centered><Loader2 size={20} className="spin" /> <span style={{ marginLeft: 8 }}>Loading…</span></Centered>
  }
  if (error && !invoice) {
    return <Centered>{error}</Centered>
  }
  if (!invoice) return null

  const isPaid = invoice.status === 'paid' || invoice.balance_due <= 0

  return (
    <div style={{ minHeight: '100vh', background: 'var(--color-paper, #faf8f5)', padding: '32px 16px' }}>
      <div style={{
        maxWidth: 520, margin: '0 auto', background: '#fff', borderRadius: 16,
        boxShadow: '0 4px 28px rgba(0,0,0,0.08)', overflow: 'hidden',
      }}>
        {/* Header */}
        <div style={{ padding: '24px 24px 16px', borderBottom: '1px solid #eee' }}>
          <div style={{ fontSize: 13, color: '#888' }}>{invoice.business_name || 'Invoice'}</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: '#1a1a1a' }}>{invoice.invoice_number}</div>
          <div style={{ fontSize: 14, color: '#666', marginTop: 4 }}>Billed to {invoice.client_name}</div>
          <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>
            Issued {fmtDate(invoice.issue_date)}{invoice.due_date && ` · Due ${fmtDate(invoice.due_date)}`}
          </div>
        </div>

        {/* Line items */}
        <div style={{ padding: '16px 24px' }}>
          {invoice.line_items.map((li, i) => (
            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid #f2f2f2', fontSize: 14 }}>
              <div>
                <div style={{ color: '#222' }}>{li.description}</div>
                <div style={{ color: '#aaa', fontSize: 12 }}>{li.quantity} × {fmt(li.unit_price)}</div>
              </div>
              <div style={{ fontWeight: 600, color: '#111' }}>{fmt(li.amount)}</div>
            </div>
          ))}

          <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 4 }}>
            <Row label="Subtotal" value={fmt(invoice.subtotal)} />
            {invoice.tax_rate > 0 && <Row label={`Tax (${invoice.tax_rate}%)`} value={fmt(invoice.tax_amount)} />}
            <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 700, fontSize: 17, borderTop: '2px solid #eee', paddingTop: 8, marginTop: 4 }}>
              <span>Total</span><span>{fmt(invoice.total)}</span>
            </div>
            {invoice.amount_paid > 0 && <Row label="Paid" value={`−${fmt(invoice.amount_paid)}`} color="#3c7850" />}
            {invoice.balance_due > 0 && (
              <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 700, fontSize: 16, color: '#1a1a1a' }}>
                <span>Balance Due</span><span>{fmt(invoice.balance_due)}</span>
              </div>
            )}
          </div>
        </div>

        {/* Pay action */}
        <div style={{ padding: '8px 24px 28px' }}>
          {isPaid ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, color: '#3c7850', fontWeight: 600, fontSize: 16, padding: '14px 0' }}>
              <CheckCircle2 size={20} strokeWidth={1.5} /> Paid in full — thank you!
            </div>
          ) : awaitingPayment ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, color: '#666', fontSize: 14, padding: '14px 0' }}>
              <Loader2 size={18} className="spin" /> Processing your payment…
            </div>
          ) : invoice.payable ? (
            <button onClick={handlePay} disabled={paying} style={{
              width: '100%', height: 50, background: '#1a5a75', color: '#fff', border: 'none',
              borderRadius: 10, fontSize: 16, fontWeight: 600, cursor: paying ? 'not-allowed' : 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
            }}>
              <CreditCard size={18} strokeWidth={1.5} />
              {paying ? 'Redirecting…' : `Pay ${fmt(invoice.balance_due)}`}
            </button>
          ) : (
            <div style={{ textAlign: 'center', color: '#999', fontSize: 13, padding: '14px 0' }}>
              Online payment isn&apos;t available for this invoice. Please contact {invoice.business_name || 'the business'} to arrange payment.
            </div>
          )}
          {error && <div style={{ fontSize: 13, color: '#b43c3c', marginTop: 10, textAlign: 'center' }}>{error}</div>}
          <div style={{ fontSize: 11, color: '#bbb', textAlign: 'center', marginTop: 14 }}>
            Secured by Stripe
          </div>
        </div>
      </div>

      <style>{`.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}`}</style>
    </div>
  )
}

function Row({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, color: color || '#888' }}>
      <span>{label}</span><span>{value}</span>
    </div>
  )
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#666', fontSize: 15, padding: 24, textAlign: 'center' }}>
      {children}
      <style>{`.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}`}</style>
    </div>
  )
}
