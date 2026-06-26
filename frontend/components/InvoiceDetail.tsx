'use client'
import { useState } from 'react'
import { X, CreditCard, Trash2, Send, FileText } from 'lucide-react'
import { recordPayment, deletePayment, updateInvoice, sendInvoice, invoicePdfUrl } from '@/lib/api'
import type { Invoice, InvoiceStatus } from '@/lib/types'

const STATUS_COLORS: Record<InvoiceStatus, { bg: string; text: string }> = {
  draft:   { bg: 'var(--color-ink-100)', text: 'var(--color-ink-600)' },
  sent:    { bg: 'rgba(26,90,117,0.1)', text: 'var(--color-ocean)' },
  partial: { bg: 'rgba(var(--color-gold-rgb,180,140,60),0.12)', text: 'var(--color-gold)' },
  paid:    { bg: 'rgba(var(--color-moss-rgb,60,120,80),0.12)', text: 'var(--color-moss)' },
  overdue: { bg: 'rgba(var(--color-rose-rgb,180,60,60),0.1)', text: 'var(--color-rose)' },
  void:    { bg: 'var(--color-ink-50)', text: 'var(--color-ink-400)' },
}

const PAYMENT_METHODS = ['card', 'cash', 'check', 'zelle', 'other']
const MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

function fmt(n: number) { return n.toLocaleString('en-US', { style: 'currency', currency: 'USD' }) }
function fmtDate(s: string) {
  const [y, m, d] = s.split('-')
  return `${MONTH_NAMES[parseInt(m)-1]} ${parseInt(d)}, ${y}`
}

interface Props {
  invoice: Invoice
  onUpdate: () => void
  onClose: () => void
}

export function InvoiceDetail({ invoice, onUpdate, onClose }: Props) {
  const [showPayForm, setShowPayForm] = useState(false)
  const [payAmount, setPayAmount]     = useState(String(invoice.balance_due > 0 ? invoice.balance_due.toFixed(2) : ''))
  const [payDate, setPayDate]         = useState(new Date().toISOString().slice(0, 10))
  const [payMethod, setPayMethod]     = useState('card')
  const [payNote, setPayNote]         = useState('')
  const [saving, setSaving]           = useState(false)
  const [error, setError]             = useState<string | null>(null)

  // Send-invoice state
  const [showSendForm, setShowSendForm] = useState(false)
  const [sendEmail, setSendEmail]       = useState(!!invoice.client_email)
  const [sendSms, setSendSms]           = useState(false)
  const [sending, setSending]           = useState(false)
  const [sendError, setSendError]       = useState<string | null>(null)

  const colors = STATUS_COLORS[invoice.status] ?? STATUS_COLORS.draft

  async function handleSend() {
    const channels = [sendEmail && 'email', sendSms && 'sms'].filter(Boolean) as string[]
    if (channels.length === 0) { setSendError('Pick at least one channel'); return }
    setSending(true); setSendError(null)
    try {
      await sendInvoice(invoice.id, channels)
      setShowSendForm(false)
      onUpdate()
    } catch (e: unknown) {
      setSendError(e instanceof Error ? e.message : 'Failed to send')
    } finally { setSending(false) }
  }

  async function handleRecordPayment() {
    const amt = parseFloat(payAmount)
    if (isNaN(amt) || amt <= 0) { setError('Enter a valid amount'); return }
    setSaving(true); setError(null)
    try {
      await recordPayment(invoice.id, { amount: amt, payment_date: payDate, payment_method: payMethod, notes: payNote || undefined })
      onUpdate()
      setShowPayForm(false)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed')
    } finally { setSaving(false) }
  }

  async function handleDeletePayment(pid: number) {
    if (!confirm('Remove this payment?')) return
    await deletePayment(invoice.id, pid)
    onUpdate()
  }

  async function handleVoid() {
    if (!confirm('Void this invoice? This cannot be undone.')) return
    await updateInvoice(invoice.id, { status: 'void' })
    onUpdate(); onClose()
  }

  async function handleMarkSent() {
    await updateInvoice(invoice.id, { status: 'sent' })
    onUpdate()
  }

  return (
    <>
      <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', zIndex: 200, backdropFilter: 'blur(2px)' }} />
      <div style={{
        position: 'fixed', left: 0, right: 0, bottom: 0, background: 'var(--color-paper)',
        borderTopLeftRadius: 20, borderTopRightRadius: 20,
        boxShadow: '0 -8px 40px rgba(0,0,0,0.18)',
        zIndex: 201, maxHeight: '92dvh', overflowY: 'auto',
        paddingBottom: 'env(safe-area-inset-bottom)',
      }}>
        <div style={{ display: 'flex', justifyContent: 'center', padding: '12px 0 0' }}>
          <div style={{ width: 40, height: 4, borderRadius: 2, background: 'var(--color-ink-200)' }} />
        </div>

        <div style={{ padding: '12px 20px 32px', display: 'flex', flexDirection: 'column', gap: 20 }}>
          {/* Header */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <div style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 600, color: 'var(--color-ink-900)' }}>
                {invoice.invoice_number}
              </div>
              <div style={{ fontSize: 14, color: 'var(--color-ink-500)', marginTop: 2 }}>{invoice.client_name}</div>
            </div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <span style={{ padding: '4px 10px', borderRadius: 'var(--radius-pill)', fontSize: 12, fontWeight: 600, background: colors.bg, color: colors.text, textTransform: 'capitalize' }}>
                {invoice.status}
              </span>
              <button onClick={onClose} className="dash-icon-btn"><X size={15} strokeWidth={1.5} /></button>
            </div>
          </div>

          {/* Dates */}
          <div style={{ display: 'flex', gap: 24 }}>
            <div>
              <div className="t-eyebrow" style={{ marginBottom: 2 }}>Issued</div>
              <div style={{ fontSize: 14, color: 'var(--color-ink-800)' }}>{fmtDate(invoice.issue_date)}</div>
            </div>
            {invoice.due_date && (
              <div>
                <div className="t-eyebrow" style={{ marginBottom: 2 }}>Due</div>
                <div style={{ fontSize: 14, color: invoice.status === 'overdue' ? 'var(--color-danger)' : 'var(--color-ink-800)', fontWeight: invoice.status === 'overdue' ? 600 : 400 }}>
                  {fmtDate(invoice.due_date)}
                </div>
              </div>
            )}
          </div>

          {/* Client */}
          {(invoice.client_phone || invoice.client_email || invoice.client_address) && (
            <div style={{ padding: '12px 14px', background: 'var(--color-ink-50)', borderRadius: 'var(--radius-card)', fontSize: 13, color: 'var(--color-ink-600)', lineHeight: 1.6 }}>
              {invoice.client_phone && <div>{invoice.client_phone}</div>}
              {invoice.client_email && <div>{invoice.client_email}</div>}
              {invoice.client_address && <div>{invoice.client_address}</div>}
            </div>
          )}

          {/* Line items */}
          <div>
            <div className="t-eyebrow" style={{ marginBottom: 8 }}>Line Items</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              {invoice.line_items.map((li, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--color-ink-100)', fontSize: 14 }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ color: 'var(--color-ink-800)' }}>{li.description}</div>
                    <div style={{ color: 'var(--color-ink-400)', fontSize: 12 }}>{li.quantity} × {fmt(li.unit_price)}</div>
                  </div>
                  <div className="tabular" style={{ fontWeight: 600, color: 'var(--color-ink-900)' }}>{fmt((li.amount ?? li.quantity * li.unit_price))}</div>
                </div>
              ))}
            </div>

            {/* Totals */}
            <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 4 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, color: 'var(--color-ink-500)' }}>
                <span>Subtotal</span><span className="tabular">{fmt(invoice.subtotal)}</span>
              </div>
              {invoice.tax_rate > 0 && (
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, color: 'var(--color-ink-500)' }}>
                  <span>Tax ({invoice.tax_rate}%)</span><span className="tabular">{fmt(invoice.tax_amount)}</span>
                </div>
              )}
              <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 700, fontSize: 16, borderTop: '2px solid var(--color-ink-200)', paddingTop: 8, marginTop: 4 }}>
                <span>Total</span><span className="tabular">{fmt(invoice.total)}</span>
              </div>
              {invoice.amount_paid > 0 && (
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 14, color: 'var(--color-moss)' }}>
                  <span>Paid</span><span className="tabular">−{fmt(invoice.amount_paid)}</span>
                </div>
              )}
              {invoice.balance_due > 0 && (
                <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 700, fontSize: 15, color: invoice.status === 'overdue' ? 'var(--color-danger)' : 'var(--color-ink-900)' }}>
                  <span>Balance Due</span><span className="tabular">{fmt(invoice.balance_due)}</span>
                </div>
              )}
            </div>
          </div>

          {/* Payment history */}
          {invoice.payments.length > 0 && (
            <div>
              <div className="t-eyebrow" style={{ marginBottom: 8 }}>Payments</div>
              {invoice.payments.map(p => (
                <div key={p.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--color-ink-100)', fontSize: 14 }}>
                  <div>
                    <span className="tabular" style={{ fontWeight: 600, color: 'var(--color-moss)' }}>{fmt(p.amount)}</span>
                    <span style={{ color: 'var(--color-ink-400)', marginLeft: 8 }}>{fmtDate(p.payment_date)} · {p.payment_method}</span>
                    {p.notes && <div style={{ fontSize: 12, color: 'var(--color-ink-400)' }}>{p.notes}</div>}
                  </div>
                  <button onClick={() => handleDeletePayment(p.id)} className="dash-icon-btn" style={{ color: 'var(--color-danger)' }}>
                    <Trash2 size={13} strokeWidth={1.5} />
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Notes */}
          {invoice.notes && (
            <div style={{ padding: '10px 14px', background: 'var(--color-ink-50)', borderRadius: 'var(--radius-card)', fontSize: 13, color: 'var(--color-ink-600)' }}>
              {invoice.notes}
            </div>
          )}

          {/* Sent status */}
          {invoice.sent_at && (
            <div style={{ fontSize: 12, color: 'var(--color-ink-400)' }}>
              Sent {fmtDate(invoice.sent_at.slice(0, 10))}
              {invoice.sent_channels && invoice.sent_channels.length > 0 && ` · ${invoice.sent_channels.join(', ')}`}
            </div>
          )}

          {/* Send invoice form */}
          {showSendForm && invoice.status !== 'void' && (
            <div style={{ padding: '16px', background: 'var(--color-ink-50)', borderRadius: 'var(--radius-card)', border: '1px solid var(--color-ink-200)', display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div className="t-eyebrow">Send Invoice</div>
              <div style={{ fontSize: 12, color: 'var(--color-ink-500)', marginTop: -4 }}>
                The invoice PDF is attached to the email and linked in the text.
              </div>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, color: invoice.client_email ? 'var(--color-ink-800)' : 'var(--color-ink-400)' }}>
                <input type="checkbox" checked={sendEmail} disabled={!invoice.client_email} onChange={e => setSendEmail(e.target.checked)} />
                Email {invoice.client_email ? `· ${invoice.client_email}` : '(no email on file)'}
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, color: invoice.client_phone ? 'var(--color-ink-800)' : 'var(--color-ink-400)' }}>
                <input type="checkbox" checked={sendSms} disabled={!invoice.client_phone} onChange={e => setSendSms(e.target.checked)} />
                Text {invoice.client_phone ? `· ${invoice.client_phone}` : '(no phone on file)'}
              </label>
              {sendError && <div style={{ fontSize: 13, color: 'var(--color-danger)' }}>{sendError}</div>}
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={handleSend} disabled={sending} className="btn-primary" style={{ flex: 1, height: 40, fontSize: 14 }}>
                  {sending ? 'Sending…' : 'Send'}
                </button>
                <button onClick={() => setShowSendForm(false)} className="btn-secondary" style={{ height: 40, padding: '0 16px', fontSize: 14 }}>Cancel</button>
              </div>
            </div>
          )}

          {/* Record payment form */}
          {showPayForm && invoice.status !== 'void' && invoice.status !== 'paid' && (
            <div style={{ padding: '16px', background: 'var(--color-ink-50)', borderRadius: 'var(--radius-card)', border: '1px solid var(--color-ink-200)', display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div className="t-eyebrow">Record Payment</div>
              <div style={{ display: 'flex', gap: 10 }}>
                <div style={{ flex: 1 }}>
                  <label className="t-label" style={{ display: 'block', marginBottom: 4 }}>Amount</label>
                  <input type="number" step="0.01" min="0" value={payAmount} onChange={e => setPayAmount(e.target.value)} className="drawer-input" style={{ width: '100%', boxSizing: 'border-box' }} />
                </div>
                <div style={{ flex: 1 }}>
                  <label className="t-label" style={{ display: 'block', marginBottom: 4 }}>Date</label>
                  <input type="date" value={payDate} onChange={e => setPayDate(e.target.value)} className="drawer-input" style={{ width: '100%', boxSizing: 'border-box' }} />
                </div>
              </div>
              <div style={{ display: 'flex', gap: 10 }}>
                <div style={{ flex: 1 }}>
                  <label className="t-label" style={{ display: 'block', marginBottom: 4 }}>Method</label>
                  <select value={payMethod} onChange={e => setPayMethod(e.target.value)} className="select-field" style={{ width: '100%' }}>
                    {PAYMENT_METHODS.map(m => <option key={m} value={m}>{m.charAt(0).toUpperCase() + m.slice(1)}</option>)}
                  </select>
                </div>
                <div style={{ flex: 1 }}>
                  <label className="t-label" style={{ display: 'block', marginBottom: 4 }}>Note</label>
                  <input placeholder="Optional" value={payNote} onChange={e => setPayNote(e.target.value)} className="drawer-input" style={{ width: '100%', boxSizing: 'border-box' }} />
                </div>
              </div>
              {error && <div style={{ fontSize: 13, color: 'var(--color-danger)' }}>{error}</div>}
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={handleRecordPayment} disabled={saving} className="btn-primary" style={{ flex: 1, height: 40, fontSize: 14 }}>
                  {saving ? 'Saving…' : 'Save Payment'}
                </button>
                <button onClick={() => setShowPayForm(false)} className="btn-secondary" style={{ height: 40, padding: '0 16px', fontSize: 14 }}>Cancel</button>
              </div>
            </div>
          )}

          {/* Actions */}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {invoice.status !== 'void' && invoice.status !== 'paid' && !showPayForm && (
              <button onClick={() => setShowPayForm(true)} className="btn-primary" style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1, justifyContent: 'center', height: 42, fontSize: 14 }}>
                <CreditCard size={14} strokeWidth={1.5} /> Record Payment
              </button>
            )}
            {invoice.status !== 'void' && !showSendForm && (
              <button onClick={() => setShowSendForm(true)} className="btn-secondary" style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1, justifyContent: 'center', height: 42, fontSize: 14 }}>
                <Send size={14} strokeWidth={1.5} /> Send Invoice
              </button>
            )}
            <a href={invoicePdfUrl(invoice.id)} target="_blank" rel="noopener noreferrer" className="btn-secondary" style={{ display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'center', height: 42, padding: '0 16px', fontSize: 14, textDecoration: 'none' }}>
              <FileText size={14} strokeWidth={1.5} /> PDF
            </a>
            {invoice.status === 'draft' && (
              <button onClick={handleMarkSent} className="btn-secondary" style={{ flex: 1, height: 42, fontSize: 14 }}>Mark as Sent</button>
            )}
            {invoice.status !== 'void' && invoice.status !== 'paid' && (
              <button onClick={handleVoid} className="btn-secondary" style={{ height: 42, padding: '0 16px', fontSize: 14, color: 'var(--color-danger)' }}>
                Void
              </button>
            )}
          </div>
        </div>
      </div>
    </>
  )
}
