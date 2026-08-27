'use client'
import { useState } from 'react'
import { X } from 'lucide-react'
import { createTask } from '@/lib/api'
import { DateQuickPicks } from './DateQuickPicks'
import type { TaskPriority } from '@/lib/types'

interface Props {
  leadId: number
  leadLabel: string
  onClose: () => void
  onCreated: (msg: string) => void
}

export function QuickTaskModal({ leadId, leadLabel, onClose, onCreated }: Props) {
  const [title, setTitle] = useState(`Follow up — ${leadLabel}`)
  const [dueDate, setDueDate] = useState(() => {
    const d = new Date()
    d.setDate(d.getDate() + 1)
    return d.toISOString().slice(0, 10)
  })
  const [priority, setPriority] = useState<TaskPriority>('normal')
  const [saving, setSaving] = useState(false)

  async function handleSubmit() {
    if (!title.trim() || saving) return
    setSaving(true)
    try {
      await createTask({ title: title.trim(), due_date: dueDate || undefined, priority, property_id: leadId })
      onCreated('Task created')
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div
        onClick={onClose}
        style={{ position: 'fixed', inset: 0, background: 'rgba(22,24,29,0.32)', zIndex: 200 }}
      />
      <div style={{
        position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%, -50%)',
        zIndex: 201,
        background: 'var(--color-surface)', borderRadius: 'var(--radius-modal)',
        boxShadow: 'var(--shadow-modal)', padding: '20px 22px',
        width: 340, maxWidth: 'calc(100vw - 32px)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
          <p style={{ margin: 0, fontSize: 15, fontWeight: 600, color: 'var(--color-ink-900)' }}>Add Task</p>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-ink-400)', display: 'flex' }}>
            <X size={15} strokeWidth={1.5} />
          </button>
        </div>
        <p style={{ margin: '0 0 12px', fontSize: 12, color: 'var(--color-ink-500)' }}>
          Linked to: <strong style={{ color: 'var(--color-ink-700)' }}>{leadLabel}</strong>
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <input
            type="text" value={title} onChange={e => setTitle(e.target.value)}
            className="drawer-input" style={{ width: '100%', boxSizing: 'border-box' }}
            autoFocus
            onKeyDown={e => e.key === 'Enter' && handleSubmit()}
          />
          <DateQuickPicks value={dueDate} onChange={setDueDate} />
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              type="date" value={dueDate} onChange={e => setDueDate(e.target.value)}
              className="drawer-input" style={{ flex: 1 }}
            />
            <select
              value={priority} onChange={e => setPriority(e.target.value as TaskPriority)}
              className="drawer-input" style={{ flex: 1 }}
            >
              <option value="low">Low</option>
              <option value="normal">Normal</option>
              <option value="high">High</option>
              <option value="urgent">Urgent</option>
            </select>
          </div>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button onClick={onClose} style={{
              padding: '7px 14px', background: 'transparent', color: 'var(--color-ink-600)',
              border: '1px solid var(--color-ink-200)', borderRadius: 'var(--radius-pill)', fontSize: 13, cursor: 'pointer',
            }}>Cancel</button>
            <button
              onClick={handleSubmit}
              disabled={!title.trim() || saving}
              style={{
                padding: '7px 16px', background: 'var(--color-accent)', color: 'var(--text-on-accent)',
                border: 'none', borderRadius: 'var(--radius-pill)', fontSize: 13, fontWeight: 600,
                cursor: !title.trim() || saving ? 'not-allowed' : 'pointer',
                opacity: !title.trim() || saving ? 0.6 : 1,
              }}
            >
              {saving ? 'Adding…' : 'Add Task'}
            </button>
          </div>
        </div>
      </div>
    </>
  )
}
