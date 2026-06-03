'use client'
import { useEffect, useState } from 'react'
import { CheckCircle2, Circle, X, ArrowRight, Kanban, Phone, FileText, Zap, Receipt } from 'lucide-react'
import Link from 'next/link'
import { getChecklistStatus } from '@/lib/api'
import type { ChecklistStatus } from '@/lib/types'

const STORAGE_KEY = 'axon-checklist-dismissed'

interface CheckItem {
  key: keyof ChecklistStatus
  label: string
  desc: string
  href: string
  icon: React.ReactNode
}

const ITEMS: CheckItem[] = [
  { key: 'has_leads', label: 'Run your first pipeline', desc: 'Import leads from your target area', href: '/settings', icon: <Kanban size={14} strokeWidth={1.5} /> },
  { key: 'has_contact', label: 'Contact a lead', desc: 'Log a call, email, or door knock', href: '/dashboard', icon: <Phone size={14} strokeWidth={1.5} /> },
  { key: 'has_invoice', label: 'Create your first invoice', desc: 'Send a professional invoice', href: '/bookkeeping', icon: <FileText size={14} strokeWidth={1.5} /> },
  { key: 'has_workflow', label: 'Set up a workflow rule', desc: 'Automate follow-up tasks', href: '/settings', icon: <Zap size={14} strokeWidth={1.5} /> },
  { key: 'has_expense', label: 'Log an expense', desc: 'Track a business expense', href: '/expenses', icon: <Receipt size={14} strokeWidth={1.5} /> },
]

export function GettingStartedChecklist() {
  const [status, setStatus] = useState<ChecklistStatus | null>(null)
  const [dismissed, setDismissed] = useState(true)

  useEffect(() => {
    const d = localStorage.getItem(STORAGE_KEY)
    if (d === 'true') return
    setDismissed(false)
    getChecklistStatus().then(setStatus).catch(() => {})
  }, [])

  if (dismissed || !status) return null

  const completed = ITEMS.filter(i => status[i.key]).length
  const allDone = completed === ITEMS.length
  if (allDone) return null

  function handleDismiss() {
    localStorage.setItem(STORAGE_KEY, 'true')
    setDismissed(true)
  }

  return (
    <div style={{
      marginBottom: 20,
      borderRadius: 'var(--radius-card)',
      background: 'white',
      boxShadow: 'var(--shadow-card)',
      overflow: 'hidden',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '14px 16px',
        borderBottom: '1px solid var(--color-ink-100)',
      }}>
        <div>
          <p style={{ margin: 0, fontSize: 14, fontWeight: 600, color: 'var(--color-ink-900)' }}>Getting started</p>
          <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--color-ink-400)' }}>{completed} of {ITEMS.length} complete</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {/* Progress bar */}
          <div style={{ width: 80, height: 6, background: 'var(--color-ink-100)', borderRadius: 3 }}>
            <div style={{
              height: '100%', borderRadius: 3,
              width: `${(completed / ITEMS.length) * 100}%`,
              background: 'var(--color-accent)',
              transition: 'width 0.3s',
            }} />
          </div>
          <button onClick={handleDismiss} className="dash-icon-btn borderless" style={{ padding: 4 }}>
            <X size={14} strokeWidth={1.5} />
          </button>
        </div>
      </div>
      <div style={{ padding: '4px 0' }}>
        {ITEMS.map(item => {
          const done = status[item.key]
          return (
            <Link
              key={item.key}
              href={item.href}
              style={{
                display: 'flex', alignItems: 'center', gap: 12,
                padding: '10px 16px',
                textDecoration: 'none', color: 'inherit',
                transition: 'background 0.1s',
              }}
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'var(--color-ink-50, #FAFAF9)' }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent' }}
            >
              {done ? (
                <CheckCircle2 size={18} strokeWidth={1.5} style={{ color: 'var(--color-moss)', flexShrink: 0 }} />
              ) : (
                <Circle size={18} strokeWidth={1.5} style={{ color: 'var(--color-ink-300)', flexShrink: 0 }} />
              )}
              <div style={{ flex: 1, minWidth: 0 }}>
                <p style={{
                  margin: 0, fontSize: 13, fontWeight: 500,
                  color: done ? 'var(--color-ink-400)' : 'var(--color-ink-900)',
                  textDecoration: done ? 'line-through' : 'none',
                }}>{item.label}</p>
                {!done && <p style={{ margin: '1px 0 0', fontSize: 11, color: 'var(--color-ink-400)' }}>{item.desc}</p>}
              </div>
              {!done && (
                <div style={{ color: 'var(--color-accent)', flexShrink: 0, display: 'flex', alignItems: 'center', gap: 4 }}>
                  {item.icon}
                  <ArrowRight size={12} strokeWidth={1.5} />
                </div>
              )}
            </Link>
          )
        })}
      </div>
    </div>
  )
}
