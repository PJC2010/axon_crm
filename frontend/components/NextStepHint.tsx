'use client'
import { useEffect, useState } from 'react'
import { ArrowRight, CheckCircle2 } from 'lucide-react'
import Link from 'next/link'
import { createTask, getTasks } from '@/lib/api'
import type { LeadStatus } from '@/lib/types'

interface StepConfig {
  hint: string
  actionLabel: string
  actionType: 'task' | 'link'
  taskTitle?: string
  href?: string
  /** Per-lead link target; takes precedence over `href`. */
  leadHref?: (leadId: number) => string
}

const STEPS: Record<LeadStatus, StepConfig> = {
  new: {
    hint: 'This lead hasn\'t been contacted yet.',
    actionLabel: 'Log a call',
    actionType: 'link',
    href: undefined,
  },
  contacted: {
    hint: 'You\'ve made contact — send a quote while interest is high.',
    actionLabel: 'Create quote',
    actionType: 'link',
    leadHref: id => `/bookkeeping?tab=quotes&lead=${id}`,
  },
  qualified: {
    hint: 'Lead is qualified — schedule a site visit or send the proposal.',
    actionLabel: 'Schedule site visit',
    actionType: 'task',
    taskTitle: 'Schedule site visit',
  },
  quote_sent: {
    hint: 'Quote is out — follow up in a few days if you don\'t hear back.',
    actionLabel: 'Remind me to follow up',
    actionType: 'task',
    taskTitle: 'Follow up on pending quote',
  },
  won: {
    hint: 'Deal is won — create the invoice to get paid.',
    actionLabel: 'Create invoice',
    actionType: 'link',
    leadHref: id => `/bookkeeping?tab=invoices&lead=${id}`,
  },
  lost: {
    hint: 'Mark as not interested or archive once you\'ve confirmed.',
    actionLabel: 'View pipeline',
    actionType: 'link',
    href: '/pipeline',
  },
  not_interested: {
    hint: 'This lead is not interested. No action needed.',
    actionLabel: 'View pipeline',
    actionType: 'link',
    href: '/pipeline',
  },
  converted: {
    hint: 'Lead has been converted to a customer.',
    actionLabel: 'View bookkeeping',
    actionType: 'link',
    href: '/bookkeeping',
  },
}

interface Props {
  status: LeadStatus
  leadId: number
  onToast?: (msg: string, v?: 'success' | 'error') => void
}

export function NextStepHint({ status, leadId, onToast }: Props) {
  // State is keyed by lead+status so it naturally resets when either changes,
  // and stale async results for a previous lead/status are ignored.
  const key = `${leadId}:${status}`
  const [createdKey, setCreatedKey] = useState<string | null>(null)
  const [existing, setExisting] = useState<{ key: string; exists: boolean } | null>(null)
  const [saving, setSaving] = useState(false)

  const step = STEPS[status]
  const taskTitle = step?.actionType === 'task' ? step.taskTitle : undefined

  // The "done" state is lost when the drawer unmounts, so re-derive it from the
  // server: if an open task with this step's title already exists for the lead,
  // don't offer to create it again.
  useEffect(() => {
    if (!taskTitle) return
    let cancelled = false
    getTasks({ property_id: leadId, complete: false })
      .then(tasks => {
        if (!cancelled) setExisting({ key, exists: tasks.some(t => t.title === taskTitle) })
      })
      .catch(() => {
        // If the check fails, enable the button and rely on the create-time guard.
        if (!cancelled) setExisting({ key, exists: false })
      })
    return () => { cancelled = true }
  }, [leadId, taskTitle, key])

  const checking = !!taskTitle && existing?.key !== key
  const done = createdKey === key || (existing?.key === key && existing.exists)

  if (!step) return null

  async function handleTaskAction() {
    if (!step.taskTitle || saving || done) return
    setSaving(true)
    try {
      // Guard against duplicates even if the mount-time check failed or raced.
      const openTasks = await getTasks({ property_id: leadId, complete: false })
      if (openTasks.some(t => t.title === step.taskTitle)) {
        setCreatedKey(key)
        onToast?.('Task already exists', 'success')
        return
      }
      const dueDate = new Date()
      dueDate.setDate(dueDate.getDate() + (status === 'quote_sent' ? 3 : 1))
      await createTask({
        title: step.taskTitle,
        due_date: dueDate.toISOString().slice(0, 10),
        priority: 'high',
        property_id: leadId,
      })
      setCreatedKey(key)
      onToast?.('Task created', 'success')
    } catch {
      onToast?.('Failed to create task', 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{
      margin: '10px 0 4px',
      padding: '10px 14px',
      borderRadius: 'var(--radius-card)',
      background: 'var(--color-accent-50)',
      border: '1px solid var(--color-accent-200)',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10,
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{ margin: 0, fontSize: 11, fontWeight: 600, color: 'var(--color-accent-300)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>
          Next step
        </p>
        <p style={{ margin: 0, fontSize: 12.5, color: 'var(--color-ink-700)', lineHeight: 1.4 }}>
          {step.hint}
        </p>
      </div>

      {done ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: 'var(--color-moss)', flexShrink: 0 }}>
          <CheckCircle2 size={14} strokeWidth={2} /> Done
        </div>
      ) : step.actionType === 'task' ? (
        <button
          onClick={handleTaskAction}
          disabled={saving || checking}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 4,
            padding: '5px 10px', flexShrink: 0,
            borderRadius: 'var(--radius-pill)',
            background: saving || checking ? 'var(--color-ink-300)' : 'var(--color-accent)',
            color: saving || checking ? 'var(--color-ink-900)' : 'var(--text-on-accent)', border: 'none',
            fontSize: 11, fontWeight: 600,
            cursor: saving || checking ? 'not-allowed' : 'pointer',
            whiteSpace: 'nowrap',
          }}
        >
          {saving ? 'Adding…' : step.actionLabel} {!saving && <ArrowRight size={10} strokeWidth={2.5} />}
        </button>
      ) : (step.leadHref || step.href) ? (
        <Link
          href={step.leadHref ? step.leadHref(leadId) : step.href!}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 4,
            padding: '5px 10px', flexShrink: 0,
            borderRadius: 'var(--radius-pill)',
            background: 'var(--color-accent)', color: 'var(--text-on-accent)',
            fontSize: 11, fontWeight: 600, textDecoration: 'none',
            whiteSpace: 'nowrap',
          }}
        >
          {step.actionLabel} <ArrowRight size={10} strokeWidth={2.5} />
        </Link>
      ) : null}
    </div>
  )
}
