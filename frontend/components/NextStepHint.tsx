'use client'
import { useState } from 'react'
import { ArrowRight, CheckCircle2 } from 'lucide-react'
import Link from 'next/link'
import { createTask } from '@/lib/api'
import type { LeadStatus } from '@/lib/types'

interface StepConfig {
  hint: string
  actionLabel: string
  actionType: 'task' | 'link'
  taskTitle?: string
  href?: string
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
    actionLabel: 'Remind me to send quote',
    actionType: 'task',
    taskTitle: 'Send quote',
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
    href: '/bookkeeping',
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
  const [done, setDone] = useState(false)
  const [saving, setSaving] = useState(false)

  const step = STEPS[status]
  if (!step) return null

  async function handleTaskAction() {
    if (!step.taskTitle || saving || done) return
    setSaving(true)
    try {
      const dueDate = new Date()
      dueDate.setDate(dueDate.getDate() + (status === 'quote_sent' ? 3 : 1))
      await createTask({
        title: step.taskTitle,
        due_date: dueDate.toISOString().slice(0, 10),
        priority: 'high',
        property_id: leadId,
      })
      setDone(true)
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
      background: 'var(--color-accent-50, #EBF2F7)',
      border: '1px solid var(--color-accent-200, #8ABBD4)',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10,
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{ margin: 0, fontSize: 11, fontWeight: 600, color: 'var(--color-accent)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>
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
          disabled={saving}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 4,
            padding: '5px 10px', flexShrink: 0,
            borderRadius: 'var(--radius-pill)',
            background: saving ? 'var(--color-ink-300)' : 'var(--color-accent)',
            color: 'white', border: 'none',
            fontSize: 11, fontWeight: 600,
            cursor: saving ? 'not-allowed' : 'pointer',
            whiteSpace: 'nowrap',
          }}
        >
          {saving ? 'Adding…' : step.actionLabel} {!saving && <ArrowRight size={10} strokeWidth={2.5} />}
        </button>
      ) : step.href ? (
        <Link
          href={step.href}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 4,
            padding: '5px 10px', flexShrink: 0,
            borderRadius: 'var(--radius-pill)',
            background: 'var(--color-accent)', color: 'white',
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
