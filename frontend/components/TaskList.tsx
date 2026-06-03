'use client'
import { useState } from 'react'
import { Check, Trash2, Clock, Zap } from 'lucide-react'
import Link from 'next/link'
import type { Task } from '@/lib/types'
import { completeTask, deleteTask } from '@/lib/api'

interface Props {
  tasks: Task[]
  onUpdate: () => void
  showLeadLink?: boolean
}

const PRIORITY_COLOR: Record<string, string> = {
  urgent: 'var(--color-danger)',
  high:   'var(--color-accent)',
  normal: 'var(--color-ink-400)',
  low:    'var(--color-ink-300)',
}

function fmt(date: string | null) {
  if (!date) return null
  const d = new Date(date + 'T00:00:00')
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const diff = Math.floor((d.getTime() - today.getTime()) / 86400000)
  if (diff < 0) return { label: `${Math.abs(diff)}d overdue`, overdue: true }
  if (diff === 0) return { label: 'Today', overdue: false }
  if (diff === 1) return { label: 'Tomorrow', overdue: false }
  return { label: d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }), overdue: false }
}

export function TaskList({ tasks, onUpdate, showLeadLink }: Props) {
  const [busy, setBusy] = useState<number | null>(null)

  async function handleComplete(id: number) {
    setBusy(id)
    try { await completeTask(id); onUpdate() } finally { setBusy(null) }
  }

  async function handleDelete(id: number) {
    if (!confirm('Delete this task?')) return
    setBusy(id)
    try { await deleteTask(id); onUpdate() } finally { setBusy(null) }
  }

  if (tasks.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '32px 16px' }}>
        <Zap size={36} strokeWidth={1} style={{ color: 'var(--color-ink-300)', marginBottom: 8 }} />
        <p style={{ margin: '0 0 4px', fontSize: 14, fontWeight: 500, color: 'var(--color-ink-500)' }}>No tasks here</p>
        <p style={{ margin: 0, fontSize: 12, color: 'var(--color-ink-400)' }}>
          Tasks are created automatically when you move leads through your pipeline.{' '}
          <Link href="/settings" style={{ color: 'var(--color-accent)', textDecoration: 'none' }}>Set up automations →</Link>
        </p>
      </div>
    )
  }

  return (
    <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
      {tasks.map(task => {
        const due = fmt(task.due_date)
        return (
          <li
            key={task.id}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '8px 10px',
              borderRadius: 'var(--radius-card)',
              background: 'var(--color-paper)',
              border: '1px solid var(--color-ink-200)',
              opacity: task.is_complete ? 0.5 : 1,
            }}
          >
            <button
              onClick={() => !task.is_complete && handleComplete(task.id)}
              disabled={busy === task.id || task.is_complete}
              style={{
                width: 18, height: 18, borderRadius: 4,
                border: `1.5px solid ${PRIORITY_COLOR[task.priority]}`,
                background: task.is_complete ? PRIORITY_COLOR[task.priority] : 'transparent',
                cursor: task.is_complete ? 'default' : 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
              }}
            >
              {task.is_complete && <Check size={11} color="#fff" strokeWidth={2.5} />}
            </button>

            <span style={{ flex: 1, fontSize: 13, color: 'var(--color-ink-900)', textDecoration: task.is_complete ? 'line-through' : 'none' }}>
              {task.title}
            </span>

            {due && (
              <span style={{ display: 'flex', alignItems: 'center', gap: 3, fontSize: 11, color: due.overdue ? 'var(--color-danger)' : 'var(--color-ink-400)', flexShrink: 0 }}>
                <Clock size={10} />
                {due.label}
              </span>
            )}

            <button
              onClick={() => handleDelete(task.id)}
              disabled={busy === task.id}
              className="dash-icon-btn"
              style={{ padding: 4 }}
            >
              <Trash2 size={12} strokeWidth={1.5} />
            </button>
          </li>
        )
      })}
    </ul>
  )
}
