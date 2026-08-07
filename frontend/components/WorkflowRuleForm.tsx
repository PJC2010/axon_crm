'use client'
import { useState, useEffect, FormEvent } from 'react'
import { createWorkflow, getMessageTemplates } from '@/lib/api'
import { useTerminology } from '@/hooks/useTerminology'
import { useEntitlements } from '@/hooks/useEntitlements'
import type { MessageTemplate, ModuleKey, WorkflowActionConfig, WorkflowTriggerConfig } from '@/lib/types'

const STATUSES = ['new', 'contacted', 'qualified', 'quote_sent', 'won', 'lost', 'not_interested']

// Mirrors DATE_TRIGGER_SOURCES in api/workflow_engine.py. Values are
// "source.field"; entries with a module only show when it's enabled.
const DATE_SOURCES: { value: string; label: string; module?: ModuleKey }[] = [
  { value: 'properties.last_sale_date', label: 'Last sale date' },
  { value: 'properties.refi_date', label: 'Refinance date' },
  { value: 'properties.last_storm_date', label: 'Last storm date' },
  { value: 'properties.created_at', label: 'Record created' },
  { value: 'policies.expiration_date', label: 'Policy expiration', module: 'policies' },
  { value: 'policies.effective_date', label: 'Policy effective date', module: 'policies' },
  { value: 'orders.order_date', label: 'Order date', module: 'orders' },
  { value: 'appointments.starts_at', label: 'Appointment start', module: 'appointments' },
]

const TRIGGER_OPTIONS: { value: string; label: string; module?: ModuleKey }[] = [
  { value: 'status_change', label: 'Status changes' },
  { value: 'date_offset', label: 'Date-based' },
  { value: 'inactivity', label: 'No contact in…' },
  { value: 'quote_event', label: 'Quote event' },
  { value: 'call_event', label: 'Missed call', module: 'calls' },
]

const ACTION_OPTIONS = [
  { value: 'create_task', label: 'Create task' },
  { value: 'send_notification', label: 'Email me' },
  { value: 'send_template', label: 'Message the contact' },
]

// send_template delivery modes ("single" is the one-template legacy shape).
const DELIVERY_OPTIONS = [
  { value: 'single', label: 'One template' },
  { value: 'sms_first', label: 'Text, or email if no phone' },
  { value: 'email_first', label: 'Email, or text if no email' },
  { value: 'both', label: 'Both text & email' },
]

const LABEL_STYLE = { fontSize: 12, color: 'var(--color-ink-500)', fontWeight: 500 } as const
const HINT_STYLE = { fontSize: 12, color: 'var(--color-ink-500)' } as const

export function WorkflowRuleForm({ onCreated, onCancel }: { onCreated: () => void; onCancel: () => void }) {
  const { categories, t } = useTerminology()
  const { hasModule } = useEntitlements()
  const [name, setName] = useState('')
  const [vertical, setVertical] = useState('')
  const [triggerType, setTriggerType] = useState('status_change')
  // status_change
  const [fromStatus, setFromStatus] = useState('')
  const [toStatus, setToStatus] = useState('')
  // date_offset — "source.field"
  const [dateSource, setDateSource] = useState('properties.last_sale_date')
  const [offsetDays, setOffsetDays] = useState(30)
  const [offsetDirection, setOffsetDirection] = useState<'before' | 'after'>('after')
  // inactivity
  const [inactivityDays, setInactivityDays] = useState(60)
  // quote_event
  const [quoteEvent, setQuoteEvent] = useState('sent')
  // call_event
  const [callEvent, setCallEvent] = useState('missed')
  // action
  const [delayMinutes, setDelayMinutes] = useState(0)
  const [actionType, setActionType] = useState('create_task')
  const [taskTitle, setTaskTitle] = useState('')
  const [dueDays, setDueDays] = useState(3)
  const [priority, setPriority] = useState('normal')
  const [subject, setSubject] = useState('')
  const [message, setMessage] = useState('')
  const [templateId, setTemplateId] = useState<number | ''>('')
  const [delivery, setDelivery] = useState('single')
  const [smsTemplateId, setSmsTemplateId] = useState<number | ''>('')
  const [emailTemplateId, setEmailTemplateId] = useState<number | ''>('')
  const [templates, setTemplates] = useState<MessageTemplate[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getMessageTemplates().then(setTemplates).catch(() => setTemplates([]))
  }, [])

  const triggerOptions = TRIGGER_OPTIONS.filter(t => !t.module || hasModule(t.module))
  const dateOptions = DATE_SOURCES.filter(f => !f.module || hasModule(f.module))
  const smsTemplates = templates.filter(tp => tp.channel === 'sms')
  const emailTemplates = templates.filter(tp => tp.channel === 'email')

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (!name.trim()) return
    if (triggerType === 'status_change' && !toStatus) return
    if (actionType === 'create_task' && !taskTitle.trim()) return
    if (actionType === 'send_notification' && !subject.trim()) return
    if (actionType === 'send_template') {
      if (delivery === 'single' && templateId === '') return
      if (delivery !== 'single' && (smsTemplateId === '' || emailTemplateId === '')) return
    }

    let trigger_config: WorkflowTriggerConfig = {}
    if (triggerType === 'status_change') {
      trigger_config = { ...(fromStatus ? { from_status: fromStatus } : {}), to_status: toStatus }
    } else if (triggerType === 'date_offset') {
      const [source, date_field] = dateSource.split('.')
      trigger_config = {
        source,
        date_field,
        offset_days: offsetDirection === 'before' ? -Math.abs(offsetDays) : Math.abs(offsetDays),
      }
    } else if (triggerType === 'inactivity') {
      trigger_config = { days: inactivityDays }
    } else if (triggerType === 'quote_event') {
      trigger_config = { event: quoteEvent }
    } else if (triggerType === 'call_event') {
      trigger_config = callEvent ? { event: callEvent } : {}
    }

    let action_config: WorkflowActionConfig
    if (actionType === 'create_task') {
      action_config = { title: taskTitle.trim(), due_days_offset: dueDays, priority }
    } else if (actionType === 'send_template') {
      const base = delivery === 'single'
        ? { template_id: templateId as number }
        : {
            templates: { sms: smsTemplateId as number, email: emailTemplateId as number },
            delivery: delivery as 'sms_first' | 'email_first' | 'both',
          }
      action_config = delayMinutes > 0 ? { ...base, delay_minutes: delayMinutes } : base
    } else {
      action_config = { channel: 'email', subject: subject.trim(), ...(message.trim() ? { message: message.trim() } : {}) }
    }

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
          {triggerOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
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
            <select value={dateSource} onChange={e => setDateSource(e.target.value)} className="drawer-input" style={{ width: 170 }}>
              {dateOptions.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}
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

        {triggerType === 'call_event' && (
          <select value={callEvent} onChange={e => setCallEvent(e.target.value)} className="drawer-input" style={{ width: 120 }}>
            <option value="">any</option>
            <option value="missed">call missed</option>
            <option value="busy">line busy</option>
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

        {actionType === 'send_template' && (
          templates.length > 0 ? (
            <>
              <select value={delivery} onChange={e => setDelivery(e.target.value)} className="drawer-input" style={{ width: 190 }}>
                {DELIVERY_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              {delivery === 'single' ? (
                <select value={templateId} onChange={e => setTemplateId(e.target.value ? Number(e.target.value) : '')} className="drawer-input" style={{ flex: 1, minWidth: 180 }} required>
                  <option value="">Choose a template…</option>
                  {templates.map(tpl => <option key={tpl.id} value={tpl.id}>{tpl.name} ({tpl.channel})</option>)}
                </select>
              ) : (
                <>
                  <select value={smsTemplateId} onChange={e => setSmsTemplateId(e.target.value ? Number(e.target.value) : '')} className="drawer-input" style={{ flex: 1, minWidth: 150 }} required>
                    <option value="">SMS template…</option>
                    {smsTemplates.map(tpl => <option key={tpl.id} value={tpl.id}>{tpl.name}</option>)}
                  </select>
                  <select value={emailTemplateId} onChange={e => setEmailTemplateId(e.target.value ? Number(e.target.value) : '')} className="drawer-input" style={{ flex: 1, minWidth: 150 }} required>
                    <option value="">Email template…</option>
                    {emailTemplates.map(tpl => <option key={tpl.id} value={tpl.id}>{tpl.name}</option>)}
                  </select>
                </>
              )}
              <span style={HINT_STYLE}>send after</span>
              <input type="number" value={delayMinutes} onChange={e => setDelayMinutes(Number(e.target.value))} className="drawer-input" style={{ width: 56 }} min={0} max={60} />
              <span style={HINT_STYLE}>min</span>
            </>
          ) : (
            <span style={HINT_STYLE}>Create a message template in Settings first.</span>
          )
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
    case 'call_event':
      return `call ${c.event || 'missed or busy'}`
    case 'lead_imported':
      return 'on import'
    case 'date_offset': {
      const n = c.offset_days ?? 0
      const key = `${c.source || 'properties'}.${c.date_field}`
      const fieldLabel = DATE_SOURCES.find(f => f.value === key)?.label || c.date_field
      if (n === 0) return `on ${fieldLabel}`
      return `${Math.abs(n)}d ${n < 0 ? 'before' : 'after'} ${fieldLabel}`
    }
    case 'inactivity':
      return `no contact in ${c.days ?? '?'}d`
    default:
      return `${c.from_status ? `${c.from_status} → ` : '* → '}${c.to_status || '*'}`
  }
}
