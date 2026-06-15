'use client'
import { useEffect, useState, useCallback } from 'react'
import { Plus, Download } from 'lucide-react'
import { getInvoices, invoiceExportUrl } from '@/lib/api'
import type { Invoice, InvoiceStatus, InvoiceFilters, InvoiceCreate, Lead } from '@/lib/types'
import { InvoiceForm } from './InvoiceForm'
import { InvoiceDetail } from './InvoiceDetail'

const STATUS_OPTIONS: { value: InvoiceStatus | ''; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'draft', label: 'Draft' },
  { value: 'sent', label: 'Sent' },
  { value: 'partial', label: 'Partial' },
  { value: 'paid', label: 'Paid' },
  { value: 'overdue', label: 'Overdue' },
  { value: 'void', label: 'Void' },
]

const STATUS_STYLE: Record<string, { bg: string; text: string }> = {
  draft:   { bg: 'var(--color-ink-100)', text: 'var(--color-ink-500)' },
  sent:    { bg: 'rgba(26,90,117,0.12)', text: 'var(--color-ocean)' },
  partial: { bg: 'rgba(180,140,60,0.14)', text: '#a07820' },
  paid:    { bg: 'rgba(60,120,80,0.12)', text: 'var(--color-moss)' },
  overdue: { bg: 'rgba(180,60,60,0.1)', text: 'var(--color-rose)' },
  void:    { bg: 'var(--color-ink-50)', text: 'var(--color-ink-300)' },
}

const MONTHS = [
  { value: 0, label: 'All Months' },
  { value: 1, label: 'Jan' }, { value: 2, label: 'Feb' }, { value: 3, label: 'Mar' },
  { value: 4, label: 'Apr' }, { value: 5, label: 'May' }, { value: 6, label: 'Jun' },
  { value: 7, label: 'Jul' }, { value: 8, label: 'Aug' }, { value: 9, label: 'Sep' },
  { value: 10, label: 'Oct' }, { value: 11, label: 'Nov' }, { value: 12, label: 'Dec' },
]

function fmt(n: number) { return n.toLocaleString('en-US', { style: 'currency', currency: 'USD' }) }
function fmtDate(s: string) {
  const [y, m, d] = s.split('-')
  return `${['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][parseInt(m)-1]} ${parseInt(d)}`
}

interface Props {
  year: number
  /** When set, opens the invoice builder prefilled from this lead (deep-link flow). */
  prefillLead?: Lead | null
  onToast?: (msg: string, v?: 'success' | 'error') => void
}

export function InvoiceList({ year, prefillLead, onToast }: Props) {
  const [status, setStatus]         = useState<InvoiceStatus | ''>('')
  const [month, setMonth]           = useState(0)
  const [invoices, setInvoices]     = useState<Invoice[]>([])
  const [total, setTotal]           = useState(0)
  const [page, setPage]             = useState(1)
  const [loading, setLoading]       = useState(true)
  const [showForm, setShowForm]     = useState(() => !!prefillLead)
  const [editInv, setEditInv]       = useState<Invoice | null>(null)
  const [detailInv, setDetailInv]   = useState<Invoice | null>(null)
  const PAGE_SIZE = 20

  const prefill: Partial<InvoiceCreate> | null = prefillLead ? {
    property_id: prefillLead.id,
    // Bill to the actual contact, else the assessor's owner name. Never the
    // address — that's the property line (client_address below), not a name.
    client_name: prefillLead.contact_name || prefillLead.owner_name || '',
    client_phone: prefillLead.contact_phone ?? undefined,
    client_email: prefillLead.contact_email ?? undefined,
    client_address: [prefillLead.address, prefillLead.city, prefillLead.state, prefillLead.zip].filter(Boolean).join(', ') || undefined,
  } : null

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const f: InvoiceFilters = { year, page, page_size: PAGE_SIZE }
      if (status) f.status = status as InvoiceStatus
      if (month > 0) f.month = month
      const res = await getInvoices(f)
      setInvoices(res.items)
      setTotal(res.total)
    } finally { setLoading(false) }
  }, [year, status, month, page])

  useEffect(() => { setPage(1) }, [year, status, month])
  useEffect(() => { load() }, [load])

  const totalPages = Math.ceil(total / PAGE_SIZE)

  return (
    <div>
      {/* Toolbar */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        {/* Status pills */}
        <div style={{ display: 'flex', gap: 6, overflowX: 'auto', flex: '1 1 200px' }}>
          {STATUS_OPTIONS.map(s => (
            <button key={s.value} onClick={() => setStatus(s.value)}
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
        <select value={month} onChange={e => setMonth(Number(e.target.value))} className="select-field" style={{ flex: '0 0 110px' }}>
          {MONTHS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
        </select>
        <a href={invoiceExportUrl({ year, status: status || undefined, month: month > 0 ? month : undefined })} download className="dash-icon-btn" style={{ display: 'flex', alignItems: 'center', textDecoration: 'none', color: 'inherit' }} title="Export CSV">
          <Download size={14} strokeWidth={1.5} />
        </a>
        <button onClick={() => { setEditInv(null); setShowForm(true) }} className="btn-primary" style={{ display: 'flex', alignItems: 'center', gap: 6, height: 36, padding: '0 14px', fontSize: 13 }}>
          <Plus size={13} strokeWidth={2} /> Invoice
        </button>
      </div>

      {/* List */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: 40, color: 'var(--color-ink-400)', fontSize: 14 }}>Loading…</div>
      ) : invoices.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '60px 20px' }}>
          <div style={{ fontSize: 36, marginBottom: 10 }}>📄</div>
          <div style={{ fontWeight: 600, color: 'var(--color-ink-700)', marginBottom: 8 }}>No invoices yet</div>
          <button onClick={() => { setEditInv(null); setShowForm(true) }} className="btn-primary" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 40, padding: '0 20px' }}>
            <Plus size={13} strokeWidth={2} /> Create Invoice
          </button>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {invoices.map(inv => {
            const s = STATUS_STYLE[inv.status] ?? STATUS_STYLE.draft
            return (
              <div key={inv.id}
                onClick={() => setDetailInv(inv)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 14, padding: '14px 16px',
                  background: 'var(--color-paper)', border: '1px solid var(--color-ink-200)',
                  borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)', cursor: 'pointer',
                }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--color-ink-500)' }}>{inv.invoice_number}</span>
                    <span style={{ padding: '2px 8px', borderRadius: 'var(--radius-pill)', fontSize: 11, fontWeight: 600, background: s.bg, color: s.text, textTransform: 'capitalize' }}>{inv.status}</span>
                  </div>
                  <div style={{ fontWeight: 600, fontSize: 15, color: 'var(--color-ink-900)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{inv.client_name}</div>
                  <div style={{ fontSize: 12, color: 'var(--color-ink-400)', marginTop: 2 }}>
                    {fmtDate(inv.issue_date)}{inv.due_date ? ` · Due ${fmtDate(inv.due_date)}` : ''}
                  </div>
                </div>
                <div style={{ textAlign: 'right', flexShrink: 0 }}>
                  <div className="tabular" style={{ fontWeight: 700, fontSize: 15, color: 'var(--color-ink-900)' }}>{fmt(inv.total)}</div>
                  {inv.balance_due > 0 && inv.balance_due < inv.total && (
                    <div className="tabular" style={{ fontSize: 12, color: 'var(--color-ink-400)' }}>Due {fmt(inv.balance_due)}</div>
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
        <InvoiceForm
          invoice={editInv}
          prefill={editInv ? null : prefill}
          onSaved={() => { setShowForm(false); onToast?.(editInv ? 'Invoice updated' : 'Invoice draft created', 'success'); load() }}
          onClose={() => setShowForm(false)}
        />
      )}
      {detailInv && <InvoiceDetail invoice={detailInv} onUpdate={load} onClose={() => setDetailInv(null)} />}
    </div>
  )
}
