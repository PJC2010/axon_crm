'use client'
import { Pencil, Trash2 } from 'lucide-react'
import { deleteExpense } from '@/lib/api'
import type { Expense, ExpenseCategory } from '@/lib/types'

const CATEGORY_COLORS: Record<ExpenseCategory, string> = {
  fuel:          'var(--color-ocean)',
  materials:     'var(--color-moss)',
  meals:         'var(--color-gold)',
  tools:         'var(--color-plum)',
  advertising:   'var(--color-rose)',
  subcontractor: 'var(--color-ink-600)',
  office:        'var(--color-accent)',
  other:         'var(--color-ink-400)',
}

const CATEGORY_EMOJI: Record<ExpenseCategory, string> = {
  fuel: '⛽', materials: '📦', meals: '🍽️', tools: '🔧',
  advertising: '📣', subcontractor: '👷', office: '🏢', other: '📋',
}

const CATEGORY_LABELS: Record<ExpenseCategory, string> = {
  fuel: 'Fuel', materials: 'Materials', meals: 'Meals', tools: 'Tools',
  advertising: 'Advertising', subcontractor: 'Subcontractor', office: 'Office', other: 'Other',
}

function fmt(n: number) {
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

function fmtDate(s: string) {
  const [y, m, d] = s.split('-')
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
  return `${months[parseInt(m) - 1]} ${parseInt(d)}, ${y}`
}

interface Props {
  expense: Expense
  onEdit: (e: Expense) => void
  onDeleted: () => void
}

export function ExpenseCard({ expense, onEdit, onDeleted }: Props) {
  const cat = expense.category as ExpenseCategory
  const color = CATEGORY_COLORS[cat] ?? 'var(--color-ink-400)'
  const emoji = CATEGORY_EMOJI[cat] ?? '📋'
  const label = CATEGORY_LABELS[cat] ?? cat

  async function handleDelete() {
    if (!confirm('Delete this expense?')) return
    try {
      await deleteExpense(expense.id)
      onDeleted()
    } catch {
      // ignore
    }
  }

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 14,
      padding: '14px 16px',
      background: 'var(--color-paper)',
      border: '1px solid var(--color-ink-200)',
      borderRadius: 'var(--radius-card)',
      boxShadow: 'var(--shadow-card)',
    }}>
      {/* Category dot / emoji */}
      <div style={{
        width: 42, height: 42, borderRadius: 10,
        background: color + '18',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexShrink: 0, fontSize: 20,
        border: `1.5px solid ${color}30`,
      }}>
        {emoji}
      </div>

      {/* Main info */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
          <span style={{ fontWeight: 600, fontSize: 15, color: 'var(--color-ink-900)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {expense.vendor}
          </span>
          <span className="tabular" style={{ fontWeight: 700, fontSize: 16, color: 'var(--color-ink-900)', flexShrink: 0 }}>
            {fmt(expense.amount)}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 3, flexWrap: 'wrap' }}>
          <span style={{
            fontSize: 11, fontWeight: 600, color, letterSpacing: '0.04em',
            textTransform: 'uppercase',
          }}>{label}</span>
          <span style={{ color: 'var(--color-ink-300)', fontSize: 11 }}>·</span>
          <span style={{ fontSize: 12, color: 'var(--color-ink-500)' }}>{fmtDate(expense.expense_date)}</span>
          {expense.is_tax_deductible && (
            <>
              <span style={{ color: 'var(--color-ink-300)', fontSize: 11 }}>·</span>
              <span style={{ fontSize: 11, color: 'var(--color-moss)', fontWeight: 600 }}>Deductible</span>
            </>
          )}
        </div>
        {expense.description && (
          <div style={{ fontSize: 12, color: 'var(--color-ink-400)', marginTop: 3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {expense.description}
          </div>
        )}
      </div>

      {/* Actions */}
      <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
        <button
          onClick={() => onEdit(expense)}
          className="dash-icon-btn"
          title="Edit"
          style={{ padding: 8 }}
        >
          <Pencil size={14} strokeWidth={1.5} />
        </button>
        <button
          onClick={handleDelete}
          className="dash-icon-btn"
          title="Delete"
          style={{ padding: 8, color: 'var(--color-danger)' }}
        >
          <Trash2 size={14} strokeWidth={1.5} />
        </button>
      </div>
    </div>
  )
}
