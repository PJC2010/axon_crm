'use client'
import { useState, FormEvent } from 'react'
import { createWorkflow } from '@/lib/api'
import { useTerminology } from '@/hooks/useTerminology'
import type { WorkflowActionConfig, WorkflowTriggerConfig } from '@/lib/types'

const STATUSES = ['new', 'contacted', 'qualified', 'quote_sent', 'won', 'lost', 'not_interested']

// Mirrors DATE_TRIGGER_SOURCES["properties"] in api/workflow_engine.py.
const DATE_FIELDS = [
  { value: 'last_sale_date', label: 'Last sale date' },
  { value: 'refi_date', label: 'Refinance date' },
  { value: 'last_storm_date', label: 'Last storm date' },
  { value: 'created_at', label: 'Record created' },
]

const TRIGGER_OPTIONS = [
  { value: 'status_change', label: 'Status changes' },
  { value: 'date_offset', label: 'Date-based' },
  { value: 'inactivity', label: 'No contact in…' },
  { value: 'quote_event', label: 'Quote event' },
]

const ACTION_OPTIONS = [
  { value: 'create_task', label: 'Create task' },
  { value: 'send_notification', label: 'Email me' },
]

const LABEL_STYLE = { fontSize: 12, color: 'var(--color-ink-500)', fontWeight: 500 } as const
const HINT_STYLE = { fontSize: 12, color: 'var(--color-ink-500)' } as const

export function WorkflowRuleForm({ onCreated, onCancel }: { onCreated: () => void; onCancel: () => void }) {
  const { categories, t } = useTerminology()
  const [name, setName] = useState('')
  const [vertical, setVertical] = useState('')
  const [triggerType, setTriggerType] = useState('status_change')
  // status_change
  const [fromStatus, setFromStatus] = useState('')
  const [toStatus, setToStatus] = useState('')
  // date_offset
  const [dateField, setDateField] = useState('last_sale_date')
  const [offsetDays, setOffsetDays] = useState(30)
  const [offsetDirection, setOffsetDirection] = useState<'before' | 'after'>('after')
  // inactivity
  const [inactivityDays, setInactivityDays] = useState(60)
  // quote_event
  const [quoteEvent, setQuoteEvent] = useState('sent')
  // action
  const [actionType, setActionType] = useState('create_task')
  const [taskTitle, setTaskTitle] = useState('')
  const [dueDays, setDueDays] = useState(3)
  const [priority, setPriority] = useState('normal')
  const [subject, setSubject] = useState('')
  const [message, setMessage] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (!name.trim()) return
    if (triggerType === 'status_change' && !toStatus) return
    if (actionType === 'create_task' && !taskTitle.trim()) return
    if (actionType === 'send_notification' && !subject.trim()) return

    let trigger_config: WorkflowTriggerConfig = {}
    if (triggerType === 'status_change') {
      trigger_config = { ...(fromStatus ? { from_status: fromStatus } : {}), to_status: toStatus }
    } else if (triggerType === 'date_offset') {
      trigger_config = {
        source: 'properties',
        date_field: dateField,
        offset_days: offsetDirection === 'before' ? -Math.abs(offsetDays) : Math.abs(offsetDays),
      }
    } else if (triggerType === 'inactivity') {
      trigger_config = { days: inactivityDays }
    } else if (triggerType === 'quote_event') {
      trigger_config = { event: quoteEvent }
    }

    const action_config: WorkflowActionConfig =
      actionType === 'create_task'
        ? { title: taskTitle.trim(), due_days_offset: dueDays, priority }
        : { channel: 'email', subject: subject.trim(), ...(message.trim() ? { message: message.trim() } : {}) }

    setSaving(true)
    try {
      await createWorkflow({
        name: name.trim(),
        trigger_type: triggerType,
        trigger_config,
        action_type: actionType,
        action_config,
        vertical: vertical || undefined,
      })
      onCreated()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to create rule')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      style={{
        display: 'flex', flexDirection: 'column', gap: 10, padding: 16,
        background: 'var(--color-surface)', borderRadius: 'var(--radius-card)',
        border: '1px solid var(--color-ink-200)', marginBottom: 16,
      }}
    >
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <input type="text" value={name} onChange={e => setName(e.target.value)} placeholder="Rule name" className="drawer-input" style={{ flex: 1, minWidth: 140 }} required />
        <select value={vertical} onChange={e => setVertical(e.target.value)} className="drawer-input">
          <option value="">All {t('categories').toLowerCase()}</option>
          {categories.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={LABEL_STYLE}>When</span>
        <select value={triggerType} onChange={e => setTriggerType(e.target.value)} className="drawer-input" style={{ width: 150 }}>
          {TRIGGER_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>

        {triggerType === 'status_change' && (
          <>
            <select value={fromStatus} onChange={e => setFromStatus(e.target.value)} className="drawer-input" style={{ width: 120 }}>
              <option value="">from any</option>
              {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
            <span style={HINT_STYLE}>to</span>
            <select value={toStatus} onChange={e => setToStatus(e.target.value)} className="drawer-input" style={{ width: 120 }} required>
              <option value="">select…</option>
              {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </>
        )}

        {triggerType === 'date_offset' && (
          <>
            <input type="number" value={offsetDays} onChange={e => setOffsetDays(Number(e.target.value))} className="drawer-input" style={{ width: 64 }} min={0} max={365} />
            <span style={HINT_STYLE}>days</span>
            <select value={offsetDirection} onChange={e => setOffsetDirection(e.target.value as 'before' | 'after')} className="drawer-input" style={{ width: 90 }}>
              <option value="after">after</option>
              <option value="before">before</option>
            </select>
            <select value={dateField} onChange={e => setDateField(e.target.value)} className="drawer-input" style={{ width: 160 }}>
              {DATE_FIELDS.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}
            </select>
          </>
        )}

        {triggerType === 'inactivity' && (
          <>
            <span style={HINT_STYLE}>no contact in</span>
            <input type="number" value={inactivityDays} onChange={e => setInactivityDays(Number(e.target.value))} className="drawer-input" style={{ width: 64 }} min={1} max={730} />
            <span style={HINT_STYLE}>days</span>
          </>
        )}

        {triggerType === 'quote_event' && (
          <select value={quoteEvent} onChange={e => setQuoteEvent(e.target.value)} className="drawer-input" style={{ width: 120 }}>
            <option value="sent">quote sent</option>
            <option value="accepted">accepted</option>
            <option value="declined">declined</option>
          </select>
        )}
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={LABEL_STYLE}>Then</span>
        <select value={actionType} onChange={e => setActionType(e.target.value)} className="drawer-input" style={{ width: 150 }}>
          {ACTION_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>

        {actionType === 'create_task' && (
          <>
            <input type="text" value={taskTitle} onChange={e => setTaskTitle(e.target.value)} placeholder="Task title" className="drawer-input" style={{ flex: 1, minWidth: 160 }} required />
            <span style={HINT_STYLE}>due in</span>
            <input type="number" value={dueDays} onChange={e => setDueDays(Number(e.target.value))} className="drawer-input" style={{ width: 56 }} min={0} max={90} />
            <span style={HINT_STYLE}>days</span>
            <select value={priority} onChange={e => setPriority(e.target.value)} className="drawer-input" style={{ width: 90 }}>
              <option value="low">Low</option>
              <option value="normal">Normal</option>
              <option value="high">High</option>
              <option value="urgent">Urgent</option>
            </select>
          </>
        )}

        {actionType === 'send_notification' && (
          <>
            <input type="text" value={subject} onChange={e => setSubject(e.target.value)} placeholder="Email subject" className="drawer-input" style={{ flex: 1, minWidth: 160 }} required />
            <input type="text" value={message} onChange={e => setMessage(e.target.value)} placeholder="Message (optional)" className="drawer-input" style={{ flex: 1, minWidth: 160 }} />
          </>
        )}
      </div>

      {error && <p style={{ margin: 0, fontSize: 12, color: 'var(--color-danger)' }}>{error}</p>}

      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button type="button" onClick={onCancel} style={{
          padding: '0 14px', height: 32, background: 'transparent', color: 'var(--color-ink-500)',
          border: '1px solid var(--color-ink-200)', borderRadius: 'var(--radius-pill)', fontSize: 12, cursor: 'pointer',
        }}>Cancel</button>
        <button type="submit" disabled={saving} style={{
          padding: '0 14px', height: 32, background: 'var(--color-ink-900)', color: 'var(--color-paper)',
          border: 'none', borderRadius: 'var(--radius-pill)', fontSize: 12, cursor: saving ? 'not-allowed' : 'pointer',
        }}>{saving ? 'Saving…' : 'Create rule'}</button>
      </div>
    </form>
  )
}

/** Human-readable trigger summary for the rules table. */
export function describeTrigger(w: { trigger_type: string; trigger_config: WorkflowTriggerConfig }): string {
  const c = w.trigger_config
  switch (w.trigger_type) {
    case 'signal_event':
      return `signal: ${c.signal_type || 'any'}`
    case 'quote_event':
      return `quote ${c.event || 'any'}`
    case 'lead_imported':
      return 'on import'
    case 'date_offset': {
      const n = c.offset_days ?? 0
      const fieldLabel = DATE_FIELDS.find(f => f.value === c.date_field)?.label || c.date_field
      if (n === 0) return `on ${fieldLabel}`
      return `${Math.abs(n)}d ${n < 0 ? 'before' : 'after'} ${fieldLabel}`
    }
    case 'inactivity':
      return `no contact in ${c.days ?? '?'}d`
    default:
      return `${c.from_status ? `${c.from_status} → ` : '* → '}${c.to_status || '*'}`
  }
}
