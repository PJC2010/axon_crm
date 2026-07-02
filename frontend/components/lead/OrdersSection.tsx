'use client'
import { useCallback, useEffect, useState } from 'react'
import { Plus, ShoppingBag, Trash2 } from 'lucide-react'
import type { Order, OrderPage, OrderStatus } from '@/lib/types'
import { createOrder, deleteOrder, getOrders, updateOrder } from '@/lib/api'
import { useEntitlements } from '@/hooks/useEntitlements'
import { fmtCurrency } from './format'

const SECTION_BORDER: React.CSSProperties = { borderBottom: '1px solid var(--color-ink-100)' }
const STATUSES: OrderStatus[] = ['pending', 'completed', 'refunded', 'cancelled']

/**
 * Purchase history attached to a record (retail). Self-fetching by leadId;
 * renders nothing when the `orders` module is off.
 */
export function OrdersSection({ leadId }: { leadId: number }) {
  const { hasModule, loading: entLoading } = useEntitlements()
  const [page, setPage] = useState<OrderPage | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [total, setTotal] = useState('')
  const [orderDate, setOrderDate] = useState('')
  const [orderNumber, setOrderNumber] = useState('')
  const [saving, setSaving] = useState(false)

  const load = useCallback(() => {
    getOrders({ property_id: leadId, page_size: 50 }).then(setPage).catch(() => setPage(null))
  }, [leadId])

  const enabled = hasModule('orders')
  useEffect(() => { if (enabled) load() }, [enabled, load])

  if (entLoading || !enabled) return null

  const items = page?.items ?? []

  async function handleAdd() {
    if (!total) return
    setSaving(true)
    try {
      await createOrder({
        property_id: leadId,
        total: Number(total),
        order_date: orderDate || undefined,
        order_number: orderNumber.trim() || undefined,
      })
      setTotal(''); setOrderDate(''); setOrderNumber('')
      setShowForm(false)
      load()
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Failed to add order')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section style={{ padding: '16px 24px', ...SECTION_BORDER }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <ShoppingBag size={13} strokeWidth={1.5} style={{ color: 'var(--color-accent)' }} />
          <p className="t-eyebrow" style={{ margin: 0 }}>Orders</p>
        </div>
        <button onClick={() => setShowForm(s => !s)} className="dash-icon-btn" style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
          <Plus size={12} strokeWidth={1.5} /> Add
        </button>
      </div>

      {page && page.completed_count > 0 && (
        <p style={{ margin: '0 0 10px', fontSize: 12, color: 'var(--color-ink-500)' }}>
          <strong className="tabular" style={{ color: 'var(--color-ink-800)' }}>{fmtCurrency(page.lifetime_total)}</strong> lifetime
          · {page.completed_count} orders
          {page.last_order_date && <> · last {page.last_order_date}</>}
        </p>
      )}

      {showForm && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
          <input value={total} onChange={e => setTotal(e.target.value)} placeholder="Total" type="number" className="drawer-input" style={{ width: 90 }} />
          <input value={orderDate} onChange={e => setOrderDate(e.target.value)} type="date" title="Order date" className="drawer-input" style={{ width: 140 }} />
          <input value={orderNumber} onChange={e => setOrderNumber(e.target.value)} placeholder="Order # (optional)" className="drawer-input" style={{ flex: 1, minWidth: 110 }} />
          <button onClick={handleAdd} disabled={saving} className="dash-icon-btn" style={{ fontSize: 12, color: 'var(--color-accent)' }}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      )}

      {items.length === 0 ? (
        !showForm && <p style={{ margin: 0, fontSize: 12, color: 'var(--color-ink-400)' }}>No orders yet.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {items.map((o: Order) => (
            <div key={o.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
              <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {o.order_number || `Order #${o.id}`}
                {o.channel && <span style={{ color: 'var(--color-ink-400)' }}> · {o.channel}</span>}
              </span>
              {o.order_date && <span style={{ color: 'var(--color-ink-400)', fontSize: 12 }}>{o.order_date}</span>}
              <span className="tabular" style={{ color: 'var(--color-ink-800)', fontSize: 12 }}>{fmtCurrency(o.total)}</span>
              <select
                value={o.status}
                onChange={async e => { await updateOrder(o.id, { status: e.target.value as OrderStatus }); load() }}
                className="drawer-input"
                style={{ fontSize: 11, width: 100 }}
              >
                {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
              <button
                onClick={async () => { if (confirm('Delete this order?')) { await deleteOrder(o.id); load() } }}
                className="dash-icon-btn" style={{ padding: 4 }} title="Delete"
              >
                <Trash2 size={11} strokeWidth={1.5} />
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
