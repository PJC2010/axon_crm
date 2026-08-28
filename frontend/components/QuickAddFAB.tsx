'use client'
import { useState, useRef, useEffect } from 'react'
import { Plus, X, CheckSquare, Receipt, FileText } from 'lucide-react'
import { createTask, createExpense } from '@/lib/api'
import { DateQuickPicks } from './DateQuickPicks'
import { ToastStack, useToast } from './Toast'
import type { TaskPriority, ExpenseCategory, PaymentMethod } from '@/lib/types'

type Panel = 'task' | 'expense' | null

function todayStr() {
  return new Date().toISOString().slice(0, 10)
}

export function QuickAddFAB() {
  const [open, setOpen] = useState(false)
  const [panel, setPanel] = useState<Panel>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const { toasts, show: showToast, dismiss: dismissToast } = useToast()

  // Task state
  const [taskTitle, setTaskTitle] = useState('')
  const [taskDate, setTaskDate] = useState('')
  const [taskPriority, setTaskPriority] = useState<TaskPriority>('normal')
  const [taskSaving, setTaskSaving] = useState(false)

  // Expense state
  const [expAmount, setExpAmount] = useState('')
  const [expCategory, setExpCategory] = useState<ExpenseCategory>('other')
  const [expVendor, setExpVendor] = useState('')
  const [expDate, setExpDate] = useState(todayStr())
  const [expSaving, setExpSaving] = useState(false)

  useEffect(() => {
    if (!open) { setPanel(null) }
  }, [open])

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    if (open) document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  async function submitTask() {
    if (!taskTitle.trim() || taskSaving) return
    setTaskSaving(true)
    try {
      await createTask({ title: taskTitle.trim(), due_date: taskDate || undefined, priority: taskPriority })
      showToast('Task created', 'success')
      setTaskTitle(''); setTaskDate(''); setTaskPriority('normal')
      setOpen(false)
    } catch {
      showToast('Failed to create task', 'error')
    } finally {
      setTaskSaving(false)
    }
  }

  async function submitExpense() {
    const amt = parseFloat(expAmount)
    if (isNaN(amt) || amt <= 0 || !expVendor.trim() || expSaving) return
    setExpSaving(true)
    try {
      await createExpense({ amount: amt, category: expCategory, vendor: expVendor.trim(), expense_date: expDate, payment_method: 'card', is_tax_deductible: true })
      showToast('Expense logged', 'success')
      setExpAmount(''); setExpVendor(''); setExpDate(todayStr())
      setOpen(false)
    } catch {
      showToast('Failed to log expense', 'error')
    } finally {
      setExpSaving(false)
    }
  }

  const EXPENSE_CATEGORIES: { value: ExpenseCategory; label: string }[] = [
    { value: 'fuel', label: 'Fuel' },
    { value: 'materials', label: 'Materials' },
    { value: 'meals', label: 'Meals' },
    { value: 'tools', label: 'Tools' },
    { value: 'advertising', label: 'Advertising' },
    { value: 'subcontractor', label: 'Subcontractor' },
    { value: 'office', label: 'Office' },
    { value: 'other', label: 'Other' },
  ]

  return (
    <>
      <ToastStack toasts={toasts} onDismiss={dismissToast} />
      <div
        ref={containerRef}
        style={{
          /* Below the modal tier: at 300 this floated over every open form. */
          position: 'fixed', bottom: 24, right: 24, zIndex: 'var(--z-fab)',
          display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 10,
        }}
      >
        {/* Panel */}
        {open && panel && (
          <div style={{
            background: 'var(--color-surface)',
            borderRadius: 'var(--radius-modal)',
            boxShadow: 'var(--shadow-modal)',
            border: '1px solid var(--color-ink-200)',
            width: 300,
            padding: '16px 18px',
            marginBottom: 4,
          }}>
            {panel === 'task' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 2 }}>
                  <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-ink-900)' }}>Quick Task</span>
                  <button onClick={() => setPanel(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-ink-400)', display: 'flex' }}>
                    <X size={14} strokeWidth={1.5} />
                  </button>
                </div>
                <input
                  type="text"
                  value={taskTitle}
                  onChange={e => setTaskTitle(e.target.value)}
                  placeholder="What needs to be done?"
                  className="drawer-input"
                  style={{ width: '100%', boxSizing: 'border-box' }}
                  autoFocus
                  onKeyDown={e => e.key === 'Enter' && submitTask()}
                />
                <DateQuickPicks value={taskDate} onChange={setTaskDate} />
                <div style={{ display: 'flex', gap: 8 }}>
                  <input
                    type="date"
                    value={taskDate}
                    onChange={e => setTaskDate(e.target.value)}
                    className="drawer-input"
                    style={{ flex: 1 }}
                  />
                  <select
                    value={taskPriority}
                    onChange={e => setTaskPriority(e.target.value as TaskPriority)}
                    className="drawer-input"
                    style={{ flex: 1 }}
                  >
                    <option value="low">Low</option>
                    <option value="normal">Normal</option>
                    <option value="high">High</option>
                    <option value="urgent">Urgent</option>
                  </select>
                </div>
                <button
                  onClick={submitTask}
                  disabled={!taskTitle.trim() || taskSaving}
                  style={{
                    padding: '8px 16px', background: 'var(--color-accent)', color: 'var(--text-on-accent)',
                    border: 'none', borderRadius: 'var(--radius-pill)', fontSize: 13, fontWeight: 600,
                    cursor: !taskTitle.trim() || taskSaving ? 'not-allowed' : 'pointer',
                    opacity: !taskTitle.trim() || taskSaving ? 0.6 : 1,
                    alignSelf: 'flex-end',
                  }}
                >
                  {taskSaving ? 'Adding…' : 'Add Task'}
                </button>
              </div>
            )}

            {panel === 'expense' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 2 }}>
                  <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-ink-900)' }}>Quick Expense</span>
                  <button onClick={() => setPanel(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-ink-400)', display: 'flex' }}>
                    <X size={14} strokeWidth={1.5} />
                  </button>
                </div>
                <div style={{ position: 'relative' }}>
                  <span style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', fontSize: 16, color: 'var(--color-ink-500)' }}>$</span>
                  <input
                    type="number" step="0.01" min="0" placeholder="0.00"
                    value={expAmount} onChange={e => setExpAmount(e.target.value)}
                    className="drawer-input"
                    style={{ width: '100%', boxSizing: 'border-box', paddingLeft: 26, fontSize: 18, fontWeight: 600 }}
                    autoFocus
                  />
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <select
                    value={expCategory}
                    onChange={e => setExpCategory(e.target.value as ExpenseCategory)}
                    className="drawer-input"
                    style={{ flex: 1 }}
                  >
                    {EXPENSE_CATEGORIES.map(c => (
                      <option key={c.value} value={c.value}>{c.label}</option>
                    ))}
                  </select>
                </div>
                <input
                  type="text" placeholder="Vendor / merchant"
                  value={expVendor} onChange={e => setExpVendor(e.target.value)}
                  className="drawer-input"
                  style={{ width: '100%', boxSizing: 'border-box' }}
                />
                <DateQuickPicks value={expDate} onChange={setExpDate} />
                <button
                  onClick={submitExpense}
                  disabled={!expAmount || !expVendor.trim() || expSaving}
                  style={{
                    padding: '8px 16px', background: 'var(--color-accent)', color: 'var(--text-on-accent)',
                    border: 'none', borderRadius: 'var(--radius-pill)', fontSize: 13, fontWeight: 600,
                    cursor: !expAmount || !expVendor.trim() || expSaving ? 'not-allowed' : 'pointer',
                    opacity: !expAmount || !expVendor.trim() || expSaving ? 0.6 : 1,
                    alignSelf: 'flex-end',
                  }}
                >
                  {expSaving ? 'Logging…' : 'Log Expense'}
                </button>
              </div>
            )}
          </div>
        )}

        {/* Action chooser */}
        {open && !panel && (
          <div style={{
            background: 'var(--color-surface)',
            borderRadius: 'var(--radius-card)',
            boxShadow: 'var(--shadow-modal)',
            border: '1px solid var(--color-ink-200)',
            padding: '8px',
            display: 'flex', flexDirection: 'column', gap: 2,
            marginBottom: 4,
          }}>
            {[
              { id: 'task' as Panel, icon: <CheckSquare size={15} strokeWidth={1.8} />, label: 'Add Task' },
              { id: 'expense' as Panel, icon: <Receipt size={15} strokeWidth={1.8} />, label: 'Log Expense' },
            ].map(item => (
              <button
                key={item.id}
                onClick={() => setPanel(item.id)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  padding: '10px 14px', minHeight: 44,
                  borderRadius: 'var(--radius-button)',
                  background: 'transparent', border: 'none',
                  cursor: 'pointer', fontSize: 14, fontWeight: 500,
                  color: 'var(--color-ink-800)', textAlign: 'left',
                  whiteSpace: 'nowrap',
                }}
                onMouseEnter={e => (e.currentTarget.style.background = 'var(--color-ink-50)')}
                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
              >
                <span style={{ color: 'var(--color-accent)', display: 'flex' }}>{item.icon}</span>
                {item.label}
              </button>
            ))}
          </div>
        )}

        {/* FAB button */}
        <button
          onClick={() => setOpen(o => !o)}
          title={open ? 'Close' : 'Quick add'}
          style={{
            width: 52, height: 52,
            borderRadius: '50%',
            background: open ? 'var(--color-ink-700)' : 'var(--color-accent)',
            color: 'var(--text-on-accent)', border: 'none',
            boxShadow: '0 4px 16px rgba(26,90,117,0.35)',
            cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            transition: 'background 0.2s, transform 0.15s',
            transform: open ? 'rotate(45deg)' : 'rotate(0deg)',
          }}
        >
          <Plus size={22} strokeWidth={2} />
        </button>
      </div>
    </>
  )
}
