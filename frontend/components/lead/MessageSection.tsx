'use client'
import { useCallback, useEffect, useState } from 'react'
import { Mail, MessageSquare, Send } from 'lucide-react'
import type { MessageTemplate } from '@/lib/types'
import { getMessageTemplates, sendLeadMessage } from '@/lib/api'

const SECTION_BORDER: React.CSSProperties = { borderBottom: '1px solid var(--color-ink-100)' }

/**
 * Send a templated email/SMS to this record's contact. Self-fetching by leadId;
 * renders nothing when the account has defined no templates (so unaffected
 * accounts don't see it). Merge fields resolve server-side.
 */
export function MessageSection({ leadId }: { leadId: number }) {
  const [templates, setTemplates] = useState<MessageTemplate[]>([])
  const [selectedId, setSelectedId] = useState<number | ''>('')
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState<string | null>(null)

  const load = useCallback(() => {
    getMessageTemplates().then(setTemplates).catch(() => setTemplates([]))
  }, [])
  useEffect(() => { load() }, [load])

  if (templates.length === 0) return null

  const selected = templates.find(t => t.id === selectedId)

  async function handleSend() {
    if (selectedId === '') return
    setSending(true)
    setResult(null)
    try {
      const res = await sendLeadMessage(leadId, { template_id: selectedId as number })
      setResult(`Sent ${res.channel} to ${res.to}`)
    } catch (err: unknown) {
      setResult(err instanceof Error ? err.message : 'Send failed')
    } finally {
      setSending(false)
    }
  }

  return (
    <section style={{ padding: '16px 24px', ...SECTION_BORDER }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 }}>
        <Send size={13} strokeWidth={1.5} style={{ color: 'var(--color-accent)' }} />
        <p className="t-eyebrow" style={{ margin: 0 }}>Send message</p>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <select
          value={selectedId}
          onChange={e => { setSelectedId(e.target.value ? Number(e.target.value) : ''); setResult(null) }}
          className="drawer-input"
          style={{ flex: 1, minWidth: 160 }}
        >
          <option value="">Choose a template…</option>
          {templates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
        <button
          onClick={handleSend}
          disabled={selectedId === '' || sending}
          className="btn-primary"
          style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 34, padding: '0 14px', fontSize: 13,
                   opacity: selectedId === '' || sending ? 0.5 : 1 }}
        >
          {selected?.channel === 'sms' ? <MessageSquare size={13} strokeWidth={1.5} /> : <Mail size={13} strokeWidth={1.5} />}
          {sending ? 'Sending…' : 'Send'}
        </button>
      </div>
      {selected?.subject && (
        <p style={{ margin: '8px 0 0', fontSize: 12, color: 'var(--color-ink-400)' }}>Subject: {selected.subject}</p>
      )}
      {result && <p style={{ margin: '8px 0 0', fontSize: 12, color: 'var(--color-ink-500)' }}>{result}</p>}
    </section>
  )
}
