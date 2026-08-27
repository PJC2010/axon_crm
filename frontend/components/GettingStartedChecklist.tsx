'use client'
import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, Circle, ArrowRight, Kanban, Phone, FileText, Zap, Receipt, ListChecks } from 'lucide-react'
import Link from 'next/link'
import { getChecklistStatus, getPreferences, updatePreferences, type UserPreferences } from '@/lib/api'
import type { ChecklistStatus } from '@/lib/types'

// Pre-server-side dismissal flag; migrated into user preferences on first load
// so the old hard dismiss doesn't resurface the card for existing users.
const LEGACY_STORAGE_KEY = 'axon-checklist-dismissed'

interface CheckItem {
  key: keyof ChecklistStatus
  label: string
  desc: string
  href: string
  icon: React.ReactNode
}

const ITEMS: CheckItem[] = [
  { key: 'has_leads', label: 'Run your first import', desc: 'Pull in leads from your target area', href: '/settings?tab=pipeline', icon: <Kanban size={14} strokeWidth={1.5} /> },
  { key: 'has_contact', label: 'Contact a lead', desc: 'Log a call, email, or door knock', href: '/dashboard', icon: <Phone size={14} strokeWidth={1.5} /> },
  { key: 'has_invoice', label: 'Create your first invoice', desc: 'Send a professional invoice', href: '/bookkeeping', icon: <FileText size={14} strokeWidth={1.5} /> },
  { key: 'has_workflow', label: 'Set up an automation', desc: 'Automate follow-up tasks', href: '/settings?tab=pipeline', icon: <Zap size={14} strokeWidth={1.5} /> },
  { key: 'has_expense', label: 'Log an expense', desc: 'Track a business expense', href: '/expenses', icon: <Receipt size={14} strokeWidth={1.5} /> },
]

export interface GettingStartedState {
  status: ChecklistStatus | null
  completed: number
  total: number
  allDone: boolean
  /** True once status + preference have loaded (avoids a flash). */
  ready: boolean
  /** "Hide for now" — kept server-side so it follows the user across devices. */
  hidden: boolean
  hide: () => void
  reveal: () => void
  /** The first not-yet-done item, for "do this next" surfaces. */
  nextItem: CheckItem | null
}

/**
 * Shared setup-progress state for the dashboard: feeds the checklist card, the
 * header "Setup 2/5" pill (the Zeigarnik tension survives hiding the card), and
 * the progressive dashboard's next-action card.
 */
export function useGettingStarted(): GettingStartedState {
  const [status, setStatus] = useState<ChecklistStatus | null>(null)
  const [hidden, setHidden] = useState(false)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [st, prefs] = await Promise.all([
          getChecklistStatus(),
          getPreferences().catch(() => ({} as UserPreferences)),
        ])
        if (cancelled) return
        setStatus(st)
        let hide = prefs.checklist_hidden
        if (hide == null && typeof window !== 'undefined'
            && localStorage.getItem(LEGACY_STORAGE_KEY) === 'true') {
          hide = true
          updatePreferences({ checklist_hidden: true }).catch(() => {})
        }
        setHidden(!!hide)
        setReady(true)
      } catch { /* stay not-ready; nothing renders */ }
    }
    load()
    return () => { cancelled = true }
  }, [])

  const hide = useCallback(() => {
    setHidden(true)
    updatePreferences({ checklist_hidden: true }).catch(() => {})
  }, [])

  const reveal = useCallback(() => {
    setHidden(false)
    updatePreferences({ checklist_hidden: false }).catch(() => {})
  }, [])

  const completed = status ? ITEMS.filter(i => status[i.key]).length : 0
  const nextItem = status ? ITEMS.find(i => !status[i.key]) ?? null : null
  return {
    status, completed, total: ITEMS.length,
    allDone: status != null && completed === ITEMS.length,
    ready, hidden, hide, reveal, nextItem,
  }
}

/** Compact header pill shown while the checklist is hidden but unfinished. */
export function SetupPill({ state }: { state: GettingStartedState }) {
  if (!state.ready || !state.hidden || state.allDone || !state.status) return null
  return (
    <button
      onClick={state.reveal}
      title="Finish setting up"
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        padding: '0 12px', minHeight: 44,
        borderRadius: 'var(--radius-pill)',
        background: 'var(--color-accent-50)',
        border: '1px solid var(--color-accent-200)',
        color: 'var(--color-accent-300)',
        fontSize: 12, fontWeight: 600,
        cursor: 'pointer', whiteSpace: 'nowrap',
      }}
    >
      <ListChecks size={13} strokeWidth={2} />
      Setup {state.completed}/{state.total}
    </button>
  )
}

export function GettingStartedChecklist({ state }: { state: GettingStartedState }) {
  const { status, completed, total, allDone, ready, hidden, hide } = state
  if (!ready || hidden || !status || allDone) return null

  return (
    <div style={{
      marginBottom: 20,
      borderRadius: 'var(--radius-card)',
      background: 'var(--color-surface)',
      boxShadow: 'var(--shadow-card)',
      overflow: 'hidden',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '14px 16px', gap: 8,
        borderBottom: '1px solid var(--color-ink-100)',
      }}>
        <div>
          <p style={{ margin: 0, fontSize: 14, fontWeight: 600, color: 'var(--color-ink-900)' }}>Getting started</p>
          <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--color-ink-400)' }}>{completed} of {total} complete</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {/* Progress bar */}
          <div style={{ width: 80, height: 6, background: 'var(--color-ink-100)', borderRadius: 3 }}>
            <div style={{
              height: '100%', borderRadius: 3,
              width: '100%',
              transform: `scaleX(${total > 0 ? completed / total : 0})`,
              transformOrigin: 'left',
              background: 'var(--color-accent)',
              transition: 'transform 0.3s',
            }} />
          </div>
          <button
            onClick={hide}
            style={{
              border: 'none', background: 'transparent', cursor: 'pointer',
              padding: '0 8px', minHeight: 44,
              fontSize: 12, fontWeight: 500, color: 'var(--color-ink-400)',
              whiteSpace: 'nowrap',
            }}
          >
            Hide for now
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
                padding: '10px 16px', minHeight: 44,
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
