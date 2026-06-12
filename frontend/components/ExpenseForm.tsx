'use client'
import { useState, useEffect, type FormEvent } from 'react'
import {
  X,
  Fuel, Package, UtensilsCrossed, Wrench, Megaphone, HardHat, Building2, ClipboardList,
  type LucideIcon,
} from 'lucide-react'
import { createExpense, updateExpense } from '@/lib/api'
import type { Expense, ExpenseCreate, ExpenseCategory, PaymentMethod } from '@/lib/types'
import { DateQuickPicks } from './DateQuickPicks'

const CATEGORIES: { value: ExpenseCategory; label: string; Icon: LucideIcon }[] = [
  { value: 'fuel',          label: 'Fuel',          Icon: Fuel },
  { value: 'materials',     label: 'Materials',     Icon: Package },
  { value: 'meals',         label: 'Meals',         Icon: UtensilsCrossed },
  { value: 'tools',         label: 'Tools',         Icon: Wrench },
  { value: 'advertising',   label: 'Advertising',   Icon: Megaphone },
  { value: 'subcontractor', label: 'Subcontractor', Icon: HardHat },
  { value: 'office',        label: 'Office',        Icon: Building2 },
  { value: 'other',         label: 'Other',         Icon: ClipboardList },
]

const PAYMENT_METHODS: { value: PaymentMethod; label: string }[] = [
  { value: 'card',  label: 'Card' },
  { value: 'cash',  label: 'Cash' },
  { value: 'check', label: 'Check' },
  { value: 'zelle', label: 'Zelle' },
  { value: 'other', label: 'Other' },
]

interface Props {
  expense?: Expense | null
  onSaved: () => void
  onClose: () => void
}

function todayStr() {
  return new Date().toISOString().slice(0, 10)
}

export function ExpenseForm({ expense, onSaved, onClose }: Props) {
  const [amount, setAmount]       = useState('')
  const [category, setCategory]   = useState<ExpenseCategory>('other')
  const [vendor, setVendor]       = useState('')
  const [description, setDesc]    = useState('')
  const [date, setDate]           = useState(todayStr())
  const [method, setMethod]       = useState<PaymentMethod>('card')
  const [deductible, setDeduct]   = useState(true)
  const [saving, setSaving]       = useState(false)
  const [error, setError]         = useState<string | null>(null)

  useEffect(() => {
    if (expense) {
      setAmount(String(expense.amount))
      setCategory(expense.category)
      setVendor(expense.vendor)
      setDesc(expense.description ?? '')
      setDate(expense.expense_date)
      setMethod(expense.payment_method)
      setDeduct(expense.is_tax_deductible)
    }
  }, [expense])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const amt = parseFloat(amount)
    if (isNaN(amt) || amt <= 0) { setError('Enter a valid amount'); return }
    if (!vendor.trim()) { setError('Vendor is required'); return }

    setSaving(true)
    setError(null)
    try {
      const body: ExpenseCreate = {
        amount: amt, category, vendor: vendor.trim(),
        description: description.trim() || undefined,
        expense_date: date, payment_method: method, is_tax_deductible: deductible,
      }
      if (expense) {
        await updateExpense(expense.id, body)
      } else {
        await createExpense(body)
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
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)',
          zIndex: 200, backdropFilter: 'blur(2px)',
        }}
      />

      {/* Drawer */}
      <div style={{
        position: 'fixed', left: 0, right: 0, bottom: 0,
        background: 'var(--color-paper)',
        borderTopLeftRadius: 20, borderTopRightRadius: 20,
        boxShadow: '0 -8px 40px rgba(0,0,0,0.18)',
        zIndex: 201, maxHeight: '92dvh', overflowY: 'auto',
        padding: '0 0 env(safe-area-inset-bottom)',
      }}>
        {/* Handle */}
        <div style={{ display: 'flex', justifyContent: 'center', padding: '12px 0 0' }}>
          <div style={{ width: 40, height: 4, borderRadius: 2, background: 'var(--color-ink-200)' }} />
        </div>

        <div style={{ padding: '12px 20px 32px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
            <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 600, color: 'var(--color-ink-900)', margin: 0 }}>
              {expense ? 'Edit Expense' : 'New Expense'}
            </h2>
            <button onClick={onClose} className="dash-icon-btn">
              <X size={16} strokeWidth={1.5} />
            </button>
          </div>

          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>

            {/* Amount — large prominent input */}
            <div>
              <label className="t-label" style={{ display: 'block', marginBottom: 6 }}>Amount</label>
              <div style={{ position: 'relative' }}>
                <span style={{
                  position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)',
                  fontSize: 22, color: 'var(--color-ink-500)', fontFamily: 'var(--font-mono)',
                }}>$</span>
                <input
                  type="number" step="0.01" min="0" placeholder="0.00"
                  value={amount} onChange={e => setAmount(e.target.value)}
                  required
                  style={{
                    width: '100%', paddingLeft: 32, paddingRight: 14, height: 56,
                    fontSize: 24, fontFamily: 'var(--font-mono)', fontWeight: 600,
                    background: 'var(--color-ink-50)', border: '1.5px solid var(--color-ink-200)',
                    borderRadius: 'var(--radius-input)', color: 'var(--color-ink-900)',
                    boxSizing: 'border-box',
                  }}
                />
              </div>
            </div>

            {/* Category grid */}
            <div>
              <label className="t-label" style={{ display: 'block', marginBottom: 8 }}>Category</label>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
                {CATEGORIES.map(c => (
                  <button
                    key={c.value} type="button"
                    onClick={() => setCategory(c.value)}
                    style={{
                      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
                      padding: '10px 4px', borderRadius: 'var(--radius-card)',
                      border: category === c.value
                        ? '2px solid var(--color-accent)'
                        : '2px solid var(--color-ink-200)',
                      background: category === c.value ? 'var(--color-accent-tint, #e8f0f4)' : 'var(--color-ink-50)',
                      cursor: 'pointer', fontSize: 11, color: category === c.value ? 'var(--color-accent)' : 'var(--color-ink-600)',
                      fontWeight: category === c.value ? 600 : 400,
                    }}
                  >
                    <c.Icon size={20} />
                    <span>{c.label}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Vendor */}
            <div>
              <label className="t-label" style={{ display: 'block', marginBottom: 6 }}>Vendor / Merchant</label>
              <input
                type="text" placeholder="e.g. Home Depot, Shell, Chick-fil-A"
                value={vendor} onChange={e => setVendor(e.target.value)}
                required className="drawer-input"
                style={{ width: '100%', boxSizing: 'border-box' }}
              />
            </div>

            {/* Date + Payment method */}
            <div style={{ display: 'flex', gap: 12 }}>
              <div style={{ flex: 1 }}>
                <label className="t-label" style={{ display: 'block', marginBottom: 6 }}>Date</label>
                <DateQuickPicks value={date} onChange={setDate} />
                <input
                  type="date" value={date} onChange={e => setDate(e.target.value)}
                  required className="drawer-input"
                  style={{ width: '100%', boxSizing: 'border-box', marginTop: 6 }}
                />
              </div>
              <div style={{ flex: 1 }}>
                <label className="t-label" style={{ display: 'block', marginBottom: 6 }}>Payment</label>
                <select
                  value={method} onChange={e => setMethod(e.target.value as PaymentMethod)}
                  className="select-field" style={{ width: '100%', boxSizing: 'border-box' }}
                >
                  {PAYMENT_METHODS.map(m => (
                    <option key={m.value} value={m.value}>{m.label}</option>
                  ))}
                </select>
              </div>
            </div>

            {/* Description */}
            <div>
              <label className="t-label" style={{ display: 'block', marginBottom: 6 }}>Note <span style={{ fontWeight: 400, color: 'var(--color-ink-400)' }}>(optional)</span></label>
              <input
                type="text" placeholder="What was this for?"
                value={description} onChange={e => setDesc(e.target.value)}
                className="drawer-input"
                style={{ width: '100%', boxSizing: 'border-box' }}
              />
            </div>

            {/* Tax deductible toggle */}
            <label style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '14px 16px', background: 'var(--color-ink-50)',
              border: '1.5px solid var(--color-ink-200)', borderRadius: 'var(--radius-card)',
              cursor: 'pointer',
            }}>
              <div>
                <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-ink-800)' }}>Tax Deductible</div>
                <div style={{ fontSize: 12, color: 'var(--color-ink-400)', marginTop: 2 }}>Include in tax summary</div>
              </div>
              <div style={{
                width: 44, height: 24, borderRadius: 12,
                background: deductible ? 'var(--color-moss)' : 'var(--color-ink-300)',
                position: 'relative', transition: 'background 0.2s', flexShrink: 0,
              }}>
                <div style={{
                  width: 18, height: 18, borderRadius: '50%', background: '#fff',
                  position: 'absolute', top: 3, left: deductible ? 23 : 3,
                  transition: 'left 0.2s', boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                }} />
              </div>
              {/* The wrapping <label> drives this checkbox, so a click anywhere on
                  the row — including the toggle above — flips state exactly once.
                  Do not add a separate onClick to the toggle div: being inside the
                  label, it would also forward the click here and double-fire. */}
              <input type="checkbox" checked={deductible} onChange={() => setDeduct(d => !d)} style={{ display: 'none' }} />
            </label>

            {error && (
              <div style={{ padding: '10px 14px', background: 'var(--color-danger-tint, #fef2f2)', border: '1px solid var(--color-danger)', borderRadius: 'var(--radius-input)', color: 'var(--color-danger)', fontSize: 13 }}>
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={saving}
              className="btn-primary"
              style={{ width: '100%', height: 50, fontSize: 15, fontWeight: 600 }}
            >
              {saving ? 'Saving…' : expense ? 'Save Changes' : 'Add Expense'}
            </button>
          </form>
        </div>
      </div>
    </>
  )
}
