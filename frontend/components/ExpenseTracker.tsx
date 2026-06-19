'use client'
import { useEffect, useState, useCallback } from 'react'
import { Plus, Download, ChevronDown, ReceiptText, Receipt, Home } from 'lucide-react'
import Link from 'next/link'
import { getExpenses, getExpenseSummary, expenseExportUrl } from '@/lib/api'
import type { Expense, ExpenseCategory, ExpenseSummary, ExpenseFilters } from '@/lib/types'
import { ExpenseSummaryBar } from './ExpenseSummaryBar'
import { ExpenseCard } from './ExpenseCard'
import { ExpenseForm } from './ExpenseForm'

const CATEGORIES: { value: ExpenseCategory | ''; label: string }[] = [
  { value: '',              label: 'All Categories' },
  { value: 'fuel',          label: 'Fuel' },
  { value: 'materials',     label: 'Materials' },
  { value: 'meals',         label: 'Meals' },
  { value: 'tools',         label: 'Tools' },
  { value: 'advertising',   label: 'Advertising' },
  { value: 'subcontractor', label: 'Subcontractor' },
  { value: 'office',        label: 'Office' },
  { value: 'other',         label: 'Other' },
]

const MONTHS = [
  { value: 0, label: 'All Months' },
  { value: 1, label: 'January' }, { value: 2, label: 'February' }, { value: 3, label: 'March' },
  { value: 4, label: 'April' },   { value: 5, label: 'May' },      { value: 6, label: 'June' },
  { value: 7, label: 'July' },    { value: 8, label: 'August' },   { value: 9, label: 'September' },
  { value: 10, label: 'October' }, { value: 11, label: 'November' }, { value: 12, label: 'December' },
]

const THIS_YEAR = new Date().getFullYear()
const YEAR_OPTIONS = Array.from({ length: 5 }, (_, i) => THIS_YEAR - i)

const EMPTY_SUMMARY: ExpenseSummary = { total: 0, by_category: {}, tax_deductible_total: 0, count: 0 }

export function ExpenseTracker() {
  const [year, setYear]               = useState(THIS_YEAR)
  const [month, setMonth]             = useState(0)
  const [category, setCategory]       = useState<ExpenseCategory | ''>('')
  const [expenses, setExpenses]       = useState<Expense[]>([])
  const [total, setTotal]             = useState(0)
  const [summary, setSummary]         = useState<ExpenseSummary>(EMPTY_SUMMARY)
  const [loadingList, setLoadingList] = useState(true)
  const [loadingSum, setLoadingSum]   = useState(true)
  const [showForm, setShowForm]       = useState(false)
  const [editTarget, setEditTarget]   = useState<Expense | null>(null)
  const [page, setPage]               = useState(1)
  const PAGE_SIZE = 25

  const buildFilters = useCallback((): ExpenseFilters => {
    const f: ExpenseFilters = { year, page, page_size: PAGE_SIZE }
    if (month > 0) f.month = month
    if (category) f.category = category as ExpenseCategory
    return f
  }, [year, month, category, page])

  const loadExpenses = useCallback(async () => {
    setLoadingList(true)
    try {
      const res = await getExpenses(buildFilters())
      setExpenses(res.items)
      setTotal(res.total)
    } finally {
      setLoadingList(false)
    }
  }, [buildFilters])

  const loadSummary = useCallback(async () => {
    setLoadingSum(true)
    try {
      const s = await getExpenseSummary(year, month > 0 ? month : undefined)
      setSummary(s)
    } finally {
      setLoadingSum(false)
    }
  }, [year, month])

  useEffect(() => {
    setPage(1)
  }, [year, month, category])

  useEffect(() => {
    loadExpenses()
  }, [loadExpenses])

  useEffect(() => {
    loadSummary()
  }, [loadSummary])

  function openAdd() {
    setEditTarget(null)
    setShowForm(true)
  }

  function openEdit(e: Expense) {
    setEditTarget(e)
    setShowForm(true)
  }

  function handleSaved() {
    setShowForm(false)
    loadExpenses()
    loadSummary()
  }

  const totalPages = Math.ceil(total / PAGE_SIZE)

  return (
    <div style={{ minHeight: '100dvh', background: 'transparent' }}>
      {/* Header */}
      <header style={{
        height: 64, padding: '0 20px', display: 'flex', alignItems: 'center',
        justifyContent: 'space-between', gap: 12,
        borderBottom: '1px solid var(--color-ink-200)',
        background: 'var(--color-paper)', position: 'sticky', top: 0, zIndex: 10,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Link href="/home" title="Home" className="dash-icon-btn" style={{ textDecoration: 'none', color: 'inherit' }}>
            <Home size={15} strokeWidth={1.5} />
          </Link>
          <ReceiptText size={18} strokeWidth={1.5} color="var(--color-accent)" className="hidden sm:block" />
          <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 600, color: 'var(--color-ink-900)', margin: 0 }}>
            Expenses
          </h1>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {/* Year picker */}
          <div style={{ position: 'relative' }}>
            <select
              value={year}
              onChange={e => setYear(Number(e.target.value))}
              className="select-field"
              style={{ paddingRight: 28, appearance: 'none', fontWeight: 600 }}
            >
              {YEAR_OPTIONS.map(y => <option key={y} value={y}>{y}</option>)}
            </select>
            <ChevronDown size={12} style={{ position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none', color: 'var(--color-ink-500)' }} />
          </div>

          {/* CSV Export */}
          <a
            href={expenseExportUrl({ year, month: month > 0 ? month : undefined, category: category || undefined })}
            download
            className="dash-icon-btn"
            title="Export CSV"
            style={{ display: 'flex', alignItems: 'center', textDecoration: 'none', color: 'inherit' }}
          >
            <Download size={14} strokeWidth={1.5} />
          </a>

          {/* Add button */}
          <button onClick={openAdd} className="btn-primary" style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '0 14px', height: 36, fontSize: 13 }}>
            <Plus size={14} strokeWidth={2} />
            <span>Add</span>
          </button>
        </div>
      </header>

      <div style={{ maxWidth: 680, margin: '0 auto', padding: '20px 16px 40px' }}>

        {/* Summary */}
        {!loadingSum && (
          <div style={{ marginBottom: 24 }}>
            <ExpenseSummaryBar summary={summary} />
          </div>
        )}

        {/* Filters */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap' }}>
          <select
            value={month}
            onChange={e => setMonth(Number(e.target.value))}
            className="select-field"
            style={{ flex: '1 1 120px', minWidth: 110 }}
          >
            {MONTHS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>

          {/* Category pills — horizontal scroll on mobile */}
          <div style={{ display: 'flex', gap: 6, overflowX: 'auto', flex: '2 1 200px', paddingBottom: 2 }}>
            {CATEGORIES.map(c => (
              <button
                key={c.value}
                onClick={() => setCategory(c.value)}
                style={{
                  flexShrink: 0, padding: '6px 12px', fontSize: 12, fontWeight: 500,
                  borderRadius: 'var(--radius-pill)',
                  border: category === c.value ? '1.5px solid var(--color-accent)' : '1.5px solid var(--color-ink-200)',
                  background: category === c.value ? 'var(--color-accent)' : 'transparent',
                  color: category === c.value ? '#fff' : 'var(--color-ink-600)',
                  cursor: 'pointer', whiteSpace: 'nowrap',
                }}
              >
                {c.label}
              </button>
            ))}
          </div>
        </div>

        {/* Expense list */}
        {loadingList ? (
          <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--color-ink-400)', fontSize: 14 }}>
            Loading…
          </div>
        ) : expenses.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '60px 20px' }}>
            <Receipt size={48} strokeWidth={1} style={{ color: 'var(--color-ink-300)', marginBottom: 12 }} />
            <div style={{ fontWeight: 600, color: 'var(--color-ink-700)', marginBottom: 6, fontSize: 16 }}>Track your first expense</div>
            <div style={{ color: 'var(--color-ink-400)', fontSize: 14, marginBottom: 20, maxWidth: 320, marginLeft: 'auto', marginRight: 'auto' }}>
              Keep track of business expenses like fuel, materials, and tools. Tax-deductible items are flagged automatically.
            </div>
            <button onClick={openAdd} className="btn-primary" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '0 20px', height: 40 }}>
              <Plus size={14} strokeWidth={2} /> Add Expense
            </button>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {expenses.map(e => (
              <ExpenseCard
                key={e.id}
                expense={e}
                onEdit={openEdit}
                onDeleted={() => { loadExpenses(); loadSummary() }}
              />
            ))}
          </div>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 12, marginTop: 24 }}>
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="btn-secondary"
              style={{ padding: '0 16px', height: 36, fontSize: 13 }}
            >
              Previous
            </button>
            <span style={{ fontSize: 13, color: 'var(--color-ink-500)' }}>{page} of {totalPages}</span>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="btn-secondary"
              style={{ padding: '0 16px', height: 36, fontSize: 13 }}
            >
              Next
            </button>
          </div>
        )}
      </div>

      {/* Add/Edit form */}
      {showForm && (
        <ExpenseForm
          expense={editTarget}
          onSaved={handleSaved}
          onClose={() => setShowForm(false)}
        />
      )}
    </div>
  )
}
