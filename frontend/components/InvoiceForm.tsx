'use client'
import { useState, useEffect, useCallback, type FormEvent } from 'react'
import { X, Plus, Trash2 } from 'lucide-react'
import { createInvoice, updateInvoice } from '@/lib/api'
import type { Invoice, InvoiceCreate, LineItem } from '@/lib/types'

const PAYMENT_METHODS = ['card', 'cash', 'check', 'zelle', 'other']

function todayStr() { return new Date().toISOString().slice(0, 10) }
function dueDateDefault() {
  const d = new Date(); d.setDate(d.getDate() + 30)
  return d.toISOString().slice(0, 10)
}
function fmt(n: number) { return n.toLocaleString('en-US', { style: 'currency', currency: 'USD' }) }

interface Props {
  invoice?: Invoice | null
  /** Seeds a fresh invoice from a lead (deep-link flow); ignored when editing. */
  prefill?: Partial<InvoiceCreate> | null
  onSaved: () => void
  onClose: () => void
}

type DraftItem = { description: string; quantity: string; unit_price: string }

function emptyItem(): DraftItem { return { description: '', quantity: '1', unit_price: '' } }

export function InvoiceForm({ invoice, prefill, onSaved, onClose }: Props) {
  // The form is mounted fresh per open, so prefill can seed state directly.
  const [clientName, setClientName]   = useState(prefill?.client_name ?? '')
  const [clientPhone, setClientPhone] = useState(prefill?.client_phone ?? '')
  const [clientEmail, setClientEmail] = useState(prefill?.client_email ?? '')
  const [clientAddr, setClientAddr]   = useState(prefill?.client_address ?? '')
  const [issueDate, setIssueDate]     = useState(todayStr())
  const [dueDate, setDueDate]         = useState(dueDateDefault())
  const [taxRate, setTaxRate]         = useState('0')
  const [notes, setNotes]             = useState('')
  const [items, setItems]             = useState<DraftItem[]>([emptyItem()])
  const [saving, setSaving]           = useState(false)
  const [error, setError]             = useState<string | null>(null)

  useEffect(() => {
    if (invoice) {
      setClientName(invoice.client_name)
      setClientPhone(invoice.client_phone ?? '')
      setClientEmail(invoice.client_email ?? '')
      setClientAddr(invoice.client_address ?? '')
      setIssueDate(invoice.issue_date)
      setDueDate(invoice.due_date ?? dueDateDefault())
      setTaxRate(String(invoice.tax_rate))
      setNotes(invoice.notes ?? '')
      setItems(invoice.line_items.length
        ? invoice.line_items.map(li => ({ description: li.description, quantity: String(li.quantity), unit_price: String(li.unit_price) }))
        : [emptyItem()]
      )
    }
  }, [invoice])

  const subtotal = items.reduce((s, item) => {
    const q = parseFloat(item.quantity) || 0
    const p = parseFloat(item.unit_price) || 0
    return s + q * p
  }, 0)
  const taxAmt = subtotal * (parseFloat(taxRate) || 0) / 100
  const total = subtotal + taxAmt

  function setItem(i: number, field: keyof DraftItem, value: string) {
    setItems(prev => prev.map((item, idx) => idx === i ? { ...item, [field]: value } : item))
  }
  function addItem() { setItems(prev => [...prev, emptyItem()]) }
  function removeItem(i: number) { setItems(prev => prev.filter((_, idx) => idx !== i)) }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!clientName.trim()) { setError('Client name is required'); return }
    if (items.some(it => !it.description.trim() || !it.unit_price)) { setError('All line items need a description and price'); return }

    setSaving(true); setError(null)
    try {
      const body: InvoiceCreate = {
        property_id: invoice?.property_id ?? prefill?.property_id,
        client_name: clientName.trim(),
        client_phone: clientPhone || undefined,
        client_email: clientEmail || undefined,
        client_address: clientAddr || undefined,
        tax_rate: parseFloat(taxRate) || 0,
        issue_date: issueDate,
        due_date: dueDate || undefined,
        notes: notes || undefined,
        line_items: items.map((it, idx) => ({
          description: it.description.trim(),
          quantity: parseFloat(it.quantity) || 1,
          unit_price: parseFloat(it.unit_price) || 0,
          sort_order: idx,
        })),
      }
      if (invoice) {
        await updateInvoice(invoice.id, body)
      } else {
        await createInvoice(body)
      }
      onSaved()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', zIndex: 200, backdropFilter: 'blur(2px)' }} />
      <div style={{
        position: 'fixed', left: 0, right: 0, bottom: 0, background: 'var(--color-paper)',
        borderTopLeftRadius: 20, borderTopRightRadius: 20,
        boxShadow: '0 -8px 40px rgba(0,0,0,0.18)',
        zIndex: 201, maxHeight: '94dvh', display: 'flex', flexDirection: 'column',
        paddingBottom: 'env(safe-area-inset-bottom)',
      }}>
        {/* Handle */}
        <div style={{ display: 'flex', justifyContent: 'center', padding: '12px 0 0', flexShrink: 0 }}>
          <div style={{ width: 40, height: 4, borderRadius: 2, background: 'var(--color-ink-200)' }} />
        </div>

        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 20px 0', flexShrink: 0 }}>
          <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 600, color: 'var(--color-ink-900)', margin: 0 }}>
            {invoice ? `Edit ${invoice.invoice_number}` : 'New Invoice'}
          </h2>
          <button onClick={onClose} className="dash-icon-btn"><X size={16} strokeWidth={1.5} /></button>
        </div>

        {/* Scrollable body */}
        <form onSubmit={handleSubmit} style={{ overflowY: 'auto', flex: 1, padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 16 }}>

          {/* Client info */}
          <div>
            <div className="t-eyebrow" style={{ marginBottom: 10 }}>Client</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <input required placeholder="Client name *" value={clientName} onChange={e => setClientName(e.target.value)} className="drawer-input" style={{ width: '100%', boxSizing: 'border-box' }} />
              <div style={{ display: 'flex', gap: 10 }}>
                <input placeholder="Phone" value={clientPhone} onChange={e => setClientPhone(e.target.value)} className="drawer-input" style={{ flex: 1, minWidth: 0 }} />
                <input placeholder="Email" type="email" value={clientEmail} onChange={e => setClientEmail(e.target.value)} className="drawer-input" style={{ flex: 1, minWidth: 0 }} />
              </div>
              <input placeholder="Address" value={clientAddr} onChange={e => setClientAddr(e.target.value)} className="drawer-input" style={{ width: '100%', boxSizing: 'border-box' }} />
            </div>
          </div>

          {/* Dates */}
          <div style={{ display: 'flex', gap: 10 }}>
            <div style={{ flex: 1 }}>
              <label className="t-label" style={{ display: 'block', marginBottom: 6 }}>Issue Date</label>
              <input type="date" value={issueDate} onChange={e => setIssueDate(e.target.value)} required className="drawer-input" style={{ width: '100%', boxSizing: 'border-box' }} />
            </div>
            <div style={{ flex: 1 }}>
              <label className="t-label" style={{ display: 'block', marginBottom: 6 }}>Due Date</label>
              <input type="date" value={dueDate} onChange={e => setDueDate(e.target.value)} className="drawer-input" style={{ width: '100%', boxSizing: 'border-box' }} />
            </div>
          </div>

          {/* Line items */}
          <div>
            <div className="t-eyebrow" style={{ marginBottom: 10 }}>Line Items</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {items.map((item, i) => (
                <div key={i} style={{ background: 'var(--color-ink-50)', borderRadius: 'var(--radius-card)', padding: '12px', border: '1px solid var(--color-ink-200)' }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                    <div style={{ flex: 1 }}>
                      <input
                        placeholder="Description"
                        value={item.description}
                        onChange={e => setItem(i, 'description', e.target.value)}
                        className="drawer-input"
                        style={{ width: '100%', boxSizing: 'border-box', marginBottom: 8 }}
                      />
                      <div style={{ display: 'flex', gap: 8 }}>
                        <div style={{ flex: '0 0 80px' }}>
                          <label style={{ fontSize: 10, color: 'var(--color-ink-400)', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'block', marginBottom: 3 }}>Qty</label>
                          <input
                            type="number" min="0.001" step="any" placeholder="1"
                            value={item.quantity} onChange={e => setItem(i, 'quantity', e.target.value)}
                            className="drawer-input" style={{ width: '100%', boxSizing: 'border-box' }}
                          />
                        </div>
                        <div style={{ flex: 1 }}>
                          <label style={{ fontSize: 10, color: 'var(--color-ink-400)', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'block', marginBottom: 3 }}>Unit Price</label>
                          <input
                            type="number" min="0" step="0.01" placeholder="0.00"
                            value={item.unit_price} onChange={e => setItem(i, 'unit_price', e.target.value)}
                            className="drawer-input" style={{ width: '100%', boxSizing: 'border-box' }}
                          />
                        </div>
                        <div style={{ flex: '0 0 80px', textAlign: 'right', paddingTop: 22 }}>
                          <span className="tabular" style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-ink-800)' }}>
                            {fmt((parseFloat(item.quantity) || 0) * (parseFloat(item.unit_price) || 0))}
                          </span>
                        </div>
                      </div>
                    </div>
                    {items.length > 1 && (
                      <button type="button" onClick={() => removeItem(i)} className="dash-icon-btn" style={{ marginTop: 4, color: 'var(--color-danger)', flexShrink: 0 }}>
                        <Trash2 size={14} strokeWidth={1.5} />
                      </button>
                    )}
                  </div>
                </div>
              ))}
              <button type="button" onClick={addItem} className="btn-secondary" style={{ display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'center', height: 38, fontSize: 13 }}>
                <Plus size={13} strokeWidth={2} /> Add Line Item
              </button>
            </div>
          </div>

          {/* Tax + Notes */}
          <div style={{ display: 'flex', gap: 10 }}>
            <div style={{ flex: '0 0 120px' }}>
              <label className="t-label" style={{ display: 'block', marginBottom: 6 }}>Tax Rate %</label>
              <input type="number" min="0" max="100" step="0.01" placeholder="0.00" value={taxRate} onChange={e => setTaxRate(e.target.value)} className="drawer-input" style={{ width: '100%', boxSizing: 'border-box' }} />
            </div>
            <div style={{ flex: 1 }}>
              <label className="t-label" style={{ display: 'block', marginBottom: 6 }}>Notes</label>
              <input placeholder="Optional notes" value={notes} onChange={e => setNotes(e.target.value)} className="drawer-input" style={{ width: '100%', boxSizing: 'border-box' }} />
            </div>
          </div>

          {error && (
            <div style={{ padding: '10px 14px', background: 'var(--color-danger-tint,#fef2f2)', border: '1px solid var(--color-danger)', borderRadius: 'var(--radius-input)', color: 'var(--color-danger)', fontSize: 13 }}>
              {error}
            </div>
          )}
        </form>

        {/* Pinned totals + submit footer */}
        <div style={{ borderTop: '1px solid var(--color-ink-200)', padding: '14px 20px', background: 'var(--color-paper)', flexShrink: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 13, color: 'var(--color-ink-600)' }}>
            <span>Subtotal</span><span className="tabular">{fmt(subtotal)}</span>
          </div>
          {(parseFloat(taxRate) || 0) > 0 && (
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 13, color: 'var(--color-ink-600)' }}>
              <span>Tax ({taxRate}%)</span><span className="tabular">{fmt(taxAmt)}</span>
            </div>
          )}
          <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 700, fontSize: 16, marginBottom: 14, color: 'var(--color-ink-900)' }}>
            <span>Total</span><span className="tabular">{fmt(total)}</span>
          </div>
          <button type="submit" form="" disabled={saving} className="btn-primary" onClick={handleSubmit as any} style={{ width: '100%', height: 50, fontSize: 15, fontWeight: 600 }}>
            {saving ? 'Saving…' : invoice ? 'Save Changes' : 'Create Invoice'}
          </button>
        </div>
      </div>
    </>
  )
}
