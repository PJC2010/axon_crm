'use client'
import { useEffect, useState, FormEvent } from 'react'
import { Plus, Trash2, Mail, MessageSquare } from 'lucide-react'
import { getMessageTemplates, createMessageTemplate, deleteMessageTemplate } from '@/lib/api'
import type { MessageChannel, MessageTemplate } from '@/lib/types'
import { useConfirm } from '@/hooks/useConfirm'

const MERGE_FIELDS = ['first_name', 'contact_name', 'address', 'owner_name', 'business_name']
// Resolve from the policy a send is about (renewal reminders); empty otherwise.
const POLICY_MERGE_FIELDS = ['policy_number', 'carrier', 'policy_type', 'premium', 'effective_date', 'expiration_date']

/**
 * Owner-facing management of message templates (email/SMS with merge fields).
 * Templates are sent to a record's contact from the record drawer or by the
 * send_template workflow action.
 */
export function MessageTemplatesSettings() {
  const [templates, setTemplates] = useState<MessageTemplate[]>([])
  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState('')
  const [channel, setChannel] = useState<MessageChannel>('email')
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { confirm, confirmDialog } = useConfirm()

  useEffect(() => {
    getMessageTemplates().then(setTemplates).catch(() => setTemplates([]))
  }, [])

  async function handleAdd(e: FormEvent) {
    e.preventDefault()
    if (!name.trim() || !body.trim()) return
    setSaving(true)
    setError(null)
    try {
      const created = await createMessageTemplate({
        name: name.trim(),
        channel,
        subject: channel === 'email' ? subject.trim() || undefined : undefined,
        body: body.trim(),
      })
      setTemplates(prev => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)))
      setName(''); setSubject(''); setBody(''); setChannel('email'); setShowForm(false)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to save template')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(id: number) {
    const ok = await confirm({
      title: 'Delete this template?',
      message: 'Workflows that send this template will stop sending it.',
      confirmLabel: 'Delete template',
      danger: true,
    })
    if (!ok) return
    await deleteMessageTemplate(id)
    setTemplates(prev => prev.filter(t => t.id !== id))
  }

  return (
    <section>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <h2 className="t-eyebrow" style={{ margin: 0 }}>Message templates</h2>
        <button onClick={() => setShowForm(s => !s)} className="dash-icon-btn"
                style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
          <Plus size={12} strokeWidth={1.5} /> New template
        </button>
      </div>
      <p style={{ fontSize: 13, color: 'var(--color-ink-400)', margin: '0 0 12px' }}>
        Reusable email/SMS with merge fields like <code>{'{{first_name}}'}</code> — send them from a
        record or a workflow. Available: {MERGE_FIELDS.map(f => <code key={f} style={{ marginRight: 6 }}>{`{{${f}}}`}</code>)}
        <br />
        For policy renewal reminders: {POLICY_MERGE_FIELDS.map(f => <code key={f} style={{ marginRight: 6 }}>{`{{${f}}}`}</code>)}
      </p>

      {templates.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 16, fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--color-ink-200)' }}>
              {['Name', 'Channel', 'Subject', ''].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--color-ink-400)', fontWeight: 500, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {templates.map(tpl => (
              <tr key={tpl.id} style={{ borderBottom: '1px solid var(--color-ink-100)' }}>
                <td style={{ padding: '8px', fontWeight: 500 }}>{tpl.name}</td>
                <td style={{ padding: '8px', color: 'var(--color-ink-500)' }}>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                    {tpl.channel === 'email' ? <Mail size={12} /> : <MessageSquare size={12} />} {tpl.channel}
                  </span>
                </td>
                <td style={{ padding: '8px', color: 'var(--color-ink-500)' }}>{tpl.subject || '—'}</td>
                <td style={{ padding: '8px', textAlign: 'right' }}>
                  <button onClick={() => handleDelete(tpl.id)} title="Delete template" className="dash-icon-btn"
                          style={{ color: 'var(--color-danger)' }}>
                    <Trash2 size={14} strokeWidth={1.5} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {showForm && (
        <form onSubmit={handleAdd} style={{
          display: 'flex', flexDirection: 'column', gap: 8, padding: 16,
          background: 'var(--color-surface)', borderRadius: 'var(--radius-card)',
          border: '1px solid var(--color-ink-200)',
        }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <input type="text" value={name} onChange={e => setName(e.target.value)} placeholder="Template name" className="drawer-input" style={{ flex: 1, minWidth: 140 }} required />
            <select value={channel} onChange={e => setChannel(e.target.value as MessageChannel)} className="drawer-input">
              <option value="email">Email</option>
              <option value="sms">SMS</option>
            </select>
          </div>
          {channel === 'email' && (
            <input type="text" value={subject} onChange={e => setSubject(e.target.value)} placeholder="Subject (supports merge fields)" className="drawer-input" />
          )}
          <textarea value={body} onChange={e => setBody(e.target.value)} placeholder="Message body — e.g. Hi {{first_name}}, your renewal is coming up." className="drawer-input" style={{ minHeight: 90, resize: 'vertical', fontFamily: 'var(--font-sans)' }} required />
          {error && <p style={{ margin: 0, fontSize: 12, color: 'var(--color-danger)' }}>{error}</p>}
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button type="button" onClick={() => setShowForm(false)} style={{
              padding: '0 14px', height: 32, background: 'transparent', color: 'var(--color-ink-500)',
              border: '1px solid var(--color-ink-200)', borderRadius: 'var(--radius-pill)', fontSize: 12, cursor: 'pointer',
            }}>Cancel</button>
            <button type="submit" disabled={saving} style={{
              padding: '0 14px', height: 32, background: 'var(--color-ink-900)', color: 'var(--color-paper)',
              border: 'none', borderRadius: 'var(--radius-pill)', fontSize: 12, cursor: saving ? 'not-allowed' : 'pointer',
            }}>{saving ? 'Saving…' : 'Save template'}</button>
          </div>
        </form>
      )}
      {confirmDialog}
    </section>
  )
}
