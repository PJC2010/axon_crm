'use client'
import { useState, FormEvent } from 'react'
import { createTask } from '@/lib/api'
import type { TaskPriority } from '@/lib/types'
import { DateQuickPicks } from './DateQuickPicks'

interface Props {
  leadId?: number
  onCreated: () => void
}

export function TaskForm({ leadId, onCreated }: Props) {
  const [title, setTitle] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [priority, setPriority] = useState<TaskPriority>('normal')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!title.trim()) return
    setLoading(true)
    try {
      await createTask({
        title: title.trim(),
        due_date: dueDate || undefined,
        priority,
        property_id: leadId,
      })
      setTitle('')
      setDueDate('')
      setPriority('normal')
      onCreated()
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <input
        type="text"
        value={title}
        onChange={e => setTitle(e.target.value)}
        placeholder="New task…"
        className="drawer-input"
        style={{ width: '100%' }}
        required
      />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <DateQuickPicks value={dueDate} onChange={setDueDate} />
        <div style={{ display: 'flex', gap: 8 }}>
        <input
          type="date"
          value={dueDate}
          onChange={e => setDueDate(e.target.value)}
          className="drawer-input"
          style={{ flex: 1 }}
        />
        <select
          value={priority}
          onChange={e => setPriority(e.target.value as TaskPriority)}
          className="drawer-input"
          style={{ flex: 1 }}
        >
          <option value="low">Low</option>
          <option value="normal">Normal</option>
          <option value="high">High</option>
          <option value="urgent">Urgent</option>
        </select>
        </div>
      </div>
      <button
        type="submit"
        disabled={loading || !title.trim()}
        style={{
          padding: '7px 14px',
          background: 'var(--color-ink-900)',
          color: 'var(--color-paper)',
          border: 'none',
          borderRadius: 'var(--radius-pill)',
          fontSize: 13,
          cursor: loading || !title.trim() ? 'not-allowed' : 'pointer',
          opacity: loading || !title.trim() ? 0.6 : 1,
          alignSelf: 'flex-end',
        }}
      >
        {loading ? 'Adding…' : 'Add task'}
      </button>
    </form>
  )
}
