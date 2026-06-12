'use client'
import { useEffect, useState } from 'react'
import { Plus, Send, FileCheck2, XCircle, Trash2, Eye, Link2 } from 'lucide-react'
import { getQuotes, getQuote, sendQuote, convertQuote, updateQuote, deleteQuote } from '@/lib/api'
import type { Quote, QuoteStatus, QuoteFilters, Lead } from '@/lib/types'
import { QuoteForm } from './QuoteForm'

const STATUS_OPTIONS: { value: QuoteStatus | ''; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'draft', label: 'Draft' },
  { value: 'sent', label: 'Sent' },
  { value: 'accepted', label: 'Accepted' },
  { value: 'declined', label: 'Declined' },
  { value: 'expired', label: 'Expired' },
]

const STATUS_STYLE: Record<string, { bg: string; text: string }> = {
  draft:    { bg: 'var(--color-ink-100)', text: 'var(--color-ink-500)' },
  sent:     { bg: 'rgba(26,90,117,0.12)', text: 'var(--color-ocean)' },
  accepted: { bg: 'rgba(60,120,80,0.12)', text: 'var(--color-moss)' },
  declined: { bg: 'rgba(180,60,60,0.1)', text: 'var(--color-rose)' },
  expired:  { bg: 'var(--color-ink-50)', text: 'var(--color-ink-300)' },
}

function fmt(n: number) { return n.toLocaleString('en-US', { style: 'currency', currency: 'USD' }) }
function fmtDate(s: string) {
  const [, m, d] = s.split('-')
  return `${['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][parseInt(m)-1]} ${parseInt(d)}`
}

interface Props {
  /** When set, opens the quote builder prefilled from this lead (deep-link flow). */
  prefillLead?: Lead | null
  onToast?: (msg: string, v?: 'success' | 'error') => void
}

export function QuoteList({ prefillLead, onToast }: Props) {
  const [status, setStatus]     = useState<QuoteStatus | ''>('')
  const [page, setPage]         = useState(1)
  const [refresh, setRefresh]   = useState(0)
  const [showForm, setShowForm] = useState(() => !!prefillLead)
  const [editQuote, setEditQuote] = useState<Quote | null>(null)
  const [busyId, setBusyId]     = useState<number | null>(null)
  const PAGE_SIZE = 20

  // Results are keyed by the filters that produced them, so "loading" is just
  // "the data on hand doesn't match the current filters" — no setState-in-effect.
  const key = `${status}:${page}:${refresh}`
  const [data, setData] = useState<{ key: string; items: Quote[]; total: number } | null>(null)

  useEffect(() => {
    let cancelled = false
    const f: QuoteFilters = { page, page_size: PAGE_SIZE }
    if (status) f.status = status
    getQuotes(f)
      .then(res => { if (!cancelled) setData({ key, items: res.items, total: res.total }) })
      .catch(() => { if (!cancelled) setData({ key, items: [], total: 0 }) })
    return () => { cancelled = true }
  }, [status, page, refresh, key])

  const loading = data?.key !== key
  const quotes = data?.items ?? []
  const total = data?.total ?? 0
  const load = () => setRefresh(r => r + 1)

  const totalPages = Math.ceil(total / PAGE_SIZE)

  const prefill = prefillLead ? {
    property_id: prefillLead.id,
    client_name: prefillLead.contact_name
      || [prefillLead.address, prefillLead.city].filter(Boolean).join(', ')
      || 'New client',
    client_phone: prefillLead.contact_phone ?? undefined,
    client_email: prefillLead.contact_email ?? undefined,
    client_address: [prefillLead.address, prefillLead.city, prefillLead.state, prefillLead.zip].filter(Boolean).join(', ') || undefined,
  } : null

  async function openEdit(q: Quote) {
    // List rows carry no line items; fetch the full quote before editing.
    try {
      setEditQuote(await getQuote(q.id))
      setShowForm(true)
    } catch {
      onToast?.('Failed to load quote', 'error')
    }
  }

  async function handleSend(q: Quote) {
    setBusyId(q.id)
    try {
      await sendQuote(q.id, q.client_email ? ['email'] : ['sms'])
      onToast?.(`Quote ${q.quote_number} sent`, 'success')
      load()
    } catch (e) {
      onToast?.(e instanceof Error ? e.message : 'Failed to send', 'error')
    } finally { setBusyId(null) }
  }

  async function handleConvert(q: Quote) {
    const msg = q.status === 'accepted'
      ? `Create an invoice for ${fmt(q.total)} from ${q.quote_number}?`
      : `Accept ${q.quote_number} and create an invoice for ${fmt(q.total)}?`
    if (!confirm(msg)) return
    setBusyId(q.id)
    try {
      const inv = await convertQuote(q.id)
      onToast?.(`Created invoice ${inv.invoice_number}`, 'success')
      load()
    } catch (e) {
      onToast?.(e instanceof Error ? e.message : 'Failed to convert', 'error')
    } finally { setBusyId(null) }
  }

  async function handleDecline(q: Quote) {
    setBusyId(q.id)
    try {
      await updateQuote(q.id, { status: 'declined' })
      onToast?.(`Quote ${q.quote_number} marked declined`, 'success')
      load()
    } catch {
      onToast?.('Failed to update', 'error')
    } finally { setBusyId(null) }
  }

  async function handleCopyLink(q: Quote) {
    if (!q.public_token) return
    try {
      await navigator.clipboard.writeText(`${window.location.origin}/q/${q.public_token}`)
      onToast?.('Quote link copied', 'success')
    } catch {
      onToast?.('Could not copy link', 'error')
    }
  }

  async function handleDelete(q: Quote) {
    if (!confirm(`Delete ${q.quote_number}? This cannot be undone.`)) return
    setBusyId(q.id)
    try {
      await deleteQuote(q.id)
      onToast?.('Quote deleted', 'success')
      load()
    } catch (e) {
      onToast?.(e instanceof Error ? e.message : 'Failed to delete', 'error')
    } finally { setBusyId(null) }
  }

  return (
    <div>
      {/* Toolbar */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: 6, overflowX: 'auto', flex: '1 1 200px' }}>
          {STATUS_OPTIONS.map(s => (
            <button key={s.value} onClick={() => { setStatus(s.value); setPage(1) }}
              style={{
                flexShrink: 0, padding: '5px 12px', fontSize: 12, fontWeight: 500,
                borderRadius: 'var(--radius-pill)', cursor: 'pointer', whiteSpace: 'nowrap',
                border: status === s.value ? '1.5px solid var(--color-accent)' : '1.5px solid var(--color-ink-200)',
                background: status === s.value ? 'var(--color-accent)' : 'transparent',
                color: status === s.value ? '#fff' : 'var(--color-ink-600)',
              }}>
              {s.label}
            </button>
          ))}
        </div>
        <button onClick={() => { setEditQuote(null); setShowForm(true) }} className="btn-primary" style={{ display: 'flex', alignItems: 'center', gap: 6, height: 36, padding: '0 14px', fontSize: 13 }}>
          <Plus size={13} strokeWidth={2} /> Quote
        </button>
      </div>

      {/* List */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: 40, color: 'var(--color-ink-400)', fontSize: 14 }}>Loading…</div>
      ) : quotes.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '60px 20px' }}>
          <div style={{ fontSize: 36, marginBottom: 10 }}>📋</div>
          <div style={{ fontWeight: 600, color: 'var(--color-ink-700)', marginBottom: 8 }}>No quotes yet</div>
          <button onClick={() => { setEditQuote(null); setShowForm(true) }} className="btn-primary" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 40, padding: '0 20px' }}>
            <Plus size={13} strokeWidth={2} /> Create Quote
          </button>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {quotes.map(q => {
            const s = STATUS_STYLE[q.status] ?? STATUS_STYLE.draft
            const busy = busyId === q.id
            const open = q.status === 'draft' || q.status === 'sent'
            // Accepted quotes still need converting — that's the moment the
            // invoice gets created, so keep the action until it's invoiced.
            const convertible = !q.converted_invoice_id && q.status !== 'declined' && q.status !== 'expired'
            return (
              <div key={q.id}
                onClick={() => { if (!q.converted_invoice_id) openEdit(q) }}
                style={{
                  display: 'flex', alignItems: 'center', gap: 14, padding: '14px 16px',
                  background: 'var(--color-paper)', border: '1px solid var(--color-ink-200)',
                  borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)',
                  cursor: q.converted_invoice_id ? 'default' : 'pointer',
                  opacity: busy ? 0.6 : 1,
                }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--color-ink-500)' }}>{q.quote_number}</span>
                    <span style={{ padding: '2px 8px', borderRadius: 'var(--radius-pill)', fontSize: 11, fontWeight: 600, background: s.bg, color: s.text, textTransform: 'capitalize' }}>{q.status}</span>
                    {q.converted_invoice_id && (
                      <span style={{ fontSize: 11, color: 'var(--color-moss)' }}>→ invoiced</span>
                    )}
                    {q.viewed_at && !q.converted_invoice_id && (
                      <span title={`Customer viewed ${new Date(q.viewed_at).toLocaleString()}`}
                        style={{ display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 11, color: 'var(--color-ocean)' }}>
                        <Eye size={11} strokeWidth={2} /> viewed
                      </span>
                    )}
                  </div>
                  <div style={{ fontWeight: 600, fontSize: 15, color: 'var(--color-ink-900)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{q.client_name}</div>
                  <div style={{ fontSize: 12, color: 'var(--color-ink-400)', marginTop: 2 }}>
                    {fmtDate(q.issue_date)}{q.valid_until ? ` · Valid until ${fmtDate(q.valid_until)}` : ''}
                  </div>
                </div>
                <div className="tabular" style={{ fontWeight: 700, fontSize: 15, color: 'var(--color-ink-900)', flexShrink: 0 }}>{fmt(q.total)}</div>

                {/* Row actions */}
                <div style={{ display: 'flex', gap: 4, flexShrink: 0 }} onClick={e => e.stopPropagation()}>
                  {open && q.public_token && (
                    <button onClick={() => handleCopyLink(q)} disabled={busy} className="dash-icon-btn" title="Copy customer link">
                      <Link2 size={14} strokeWidth={1.5} />
                    </button>
                  )}
                  {open && (q.client_email || q.client_phone) && (
                    <button onClick={() => handleSend(q)} disabled={busy} className="dash-icon-btn" title={q.status === 'sent' ? 'Resend to client' : 'Send to client'}>
                      <Send size={14} strokeWidth={1.5} />
                    </button>
                  )}
                  {convertible && q.status === 'accepted' ? (
                    // Customer said yes — creating the invoice is the obvious
                    // next step, so it gets a labeled button, not an icon.
                    <button onClick={() => handleConvert(q)} disabled={busy} className="btn-primary"
                      style={{ display: 'inline-flex', alignItems: 'center', gap: 5, height: 30, padding: '0 12px', fontSize: 12, fontWeight: 600 }}>
                      <FileCheck2 size={13} strokeWidth={1.5} /> Create invoice
                    </button>
                  ) : convertible ? (
                    <button onClick={() => handleConvert(q)} disabled={busy} className="dash-icon-btn" title="Accept + convert to invoice" style={{ color: 'var(--color-moss)' }}>
                      <FileCheck2 size={14} strokeWidth={1.5} />
                    </button>
                  ) : null}
                  {q.status === 'sent' && (
                    <button onClick={() => handleDecline(q)} disabled={busy} className="dash-icon-btn" title="Mark declined" style={{ color: 'var(--color-rose)' }}>
                      <XCircle size={14} strokeWidth={1.5} />
                    </button>
                  )}
                  {!q.converted_invoice_id && (
                    <button onClick={() => handleDelete(q)} disabled={busy} className="dash-icon-btn" title="Delete quote" style={{ color: 'var(--color-danger)' }}>
                      <Trash2 size={14} strokeWidth={1.5} />
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={{ display: 'flex', justifyContent: 'center', gap: 12, marginTop: 20, alignItems: 'center' }}>
          <button onClick={() => setPage(p => Math.max(1, p-1))} disabled={page===1} className="btn-secondary" style={{ height: 36, padding: '0 14px', fontSize: 13 }}>Prev</button>
          <span style={{ fontSize: 13, color: 'var(--color-ink-500)' }}>{page} / {totalPages}</span>
          <button onClick={() => setPage(p => Math.min(totalPages, p+1))} disabled={page===totalPages} className="btn-secondary" style={{ height: 36, padding: '0 14px', fontSize: 13 }}>Next</button>
        </div>
      )}

      {showForm && (
        <QuoteForm
          quote={editQuote}
          prefill={editQuote ? null : prefill}
          onSaved={() => { setShowForm(false); setEditQuote(null); onToast?.(editQuote ? 'Quote updated' : 'Quote created', 'success'); load() }}
          onClose={() => { setShowForm(false); setEditQuote(null) }}
        />
      )}
    </div>
  )
}
