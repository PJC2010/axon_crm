'use client'
import { useEffect, useRef, useState } from 'react'
import { Mail, MessageSquare, Send } from 'lucide-react'
import type { ConversationMessage, Lead, MessageChannel, MessageTemplate } from '@/lib/types'
import { getConversation, getMessageTemplates, markConversationSeen, sendLeadMessage } from '@/lib/api'
import { refreshUnreadMessages } from '@/hooks/useUnreadMessages'
import { fmtDateTime } from './format'
import { MessageBubble } from './MessageBubble'

const SECTION_BORDER: React.CSSProperties = { borderBottom: '1px solid var(--color-ink-100)' }

const TEXTAREA_STYLE: React.CSSProperties = {
  width: '100%',
  fontSize: 13,
  padding: '8px 12px',
  borderRadius: 'var(--radius-input)',
  border: '1px solid var(--color-ink-200)',
  background: 'var(--color-paper)',
  color: 'var(--color-ink-900)',
  fontFamily: 'var(--font-sans)',
  resize: 'none',
  outline: 'none',
}

/** How often the thread refetches while the lead page is open, so an inbound
 *  reply shows up without a manual refresh. */
const POLL_MS = 15_000

/**
 * Two-way messaging with this record's contact: the SMS thread rendered as a
 * chat view (polling for new replies), a free-form composer, and the saved
 * template picker. Viewing the thread marks its inbound texts read, which
 * clears them from the header message bell. Merge fields in templates resolve
 * server-side.
 */
export function MessageSection({ lead }: { lead: Lead }) {
  const [thread, setThread] = useState<ConversationMessage[]>([])
  const [templates, setTemplates] = useState<MessageTemplate[]>([])
  const [selectedId, setSelectedId] = useState<number | ''>('')
  const [channel, setChannel] = useState<MessageChannel>(lead.contact_phone ? 'sms' : 'email')
  const [subject, setSubject] = useState('')
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState<string | null>(null)

  const scrollRef = useRef<HTMLDivElement>(null)
  const lastMsgId = useRef<number>(0)

  const canSms = !!lead.contact_phone
  const canEmail = !!lead.contact_email

  // Fetch the thread on mount and on a poll interval. The fetcher is local to
  // the effect (TaskBell shape) — a useCallback version trips the
  // react-hooks/set-state-in-effect lint rule.
  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const data = await getConversation(lead.id)
        if (!active) return
        setThread(data)
        // The thread is on screen, so its inbound texts are read by definition —
        // mark them and keep the header bell in sync.
        if (data.some(m => m.direction === 'inbound' && !m.seen_at)) {
          const now = new Date().toISOString()
          await markConversationSeen(lead.id).catch(() => {})
          if (!active) return
          setThread(prev => prev.map(m => m.direction === 'inbound' && !m.seen_at ? { ...m, seen_at: now } : m))
          refreshUnreadMessages()
        }
      } catch { /* lead vanished or transient — try again next tick */ }
    }
    void load()
    const id = setInterval(() => void load(), POLL_MS)
    return () => { active = false; clearInterval(id) }
  }, [lead.id])

  useEffect(() => {
    getMessageTemplates().then(setTemplates).catch(() => setTemplates([]))
  }, [])

  // Stick to the newest message like any chat view — but only when something
  // actually arrived, so the user's scroll position isn't yanked every poll.
  useEffect(() => {
    const newest = thread.length ? thread[thread.length - 1].id : 0
    if (newest !== lastMsgId.current) {
      lastMsgId.current = newest
      const el = scrollRef.current
      if (el) el.scrollTop = el.scrollHeight
    }
  }, [thread])

  // Event-handler refresh after a send; the poll effect owns the steady state.
  function refreshThread() {
    getConversation(lead.id).then(setThread).catch(() => {})
  }

  async function handleSend() {
    const body = text.trim()
    if (!body) return
    setSending(true)
    setResult(null)
    try {
      const res = await sendLeadMessage(lead.id, {
        channel,
        body,
        ...(channel === 'email' && subject.trim() ? { subject: subject.trim() } : {}),
      })
      setText('')
      setSubject('')
      setResult(`Sent ${res.channel} to ${res.to}`)
      refreshThread()
    } catch (err: unknown) {
      setResult(err instanceof Error ? err.message : 'Send failed')
    } finally {
      setSending(false)
    }
  }

  async function handleSendTemplate() {
    if (selectedId === '') return
    setSending(true)
    setResult(null)
    try {
      const res = await sendLeadMessage(lead.id, { template_id: selectedId as number })
      setResult(`Sent ${res.channel} to ${res.to}`)
      refreshThread()
    } catch (err: unknown) {
      setResult(err instanceof Error ? err.message : 'Send failed')
    } finally {
      setSending(false)
    }
  }

  const selected = templates.find(t => t.id === selectedId)

  return (
    <section style={{ padding: '16px 24px', ...SECTION_BORDER }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 }}>
        <MessageSquare size={13} strokeWidth={1.5} style={{ color: 'var(--color-accent)' }} />
        <p className="t-eyebrow" style={{ margin: 0 }}>Messages</p>
      </div>

      {/* SMS thread — chat view, newest at the bottom */}
      <div ref={scrollRef} style={{ maxHeight: 320, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
        {thread.length === 0 ? (
          <p style={{ fontSize: 12, color: 'var(--color-ink-400)', margin: 0 }}>
            No texts yet{canSms ? ' — send the first one below.' : '.'}
          </p>
        ) : thread.map(m => (
          <MessageBubble
            key={m.id}
            body={m.body}
            inbound={m.direction === 'inbound'}
            channel="sms"
            caption={fmtDateTime(m.created_at)}
          />
        ))}
      </div>

      {/* Free-form composer */}
      {canSms || canEmail ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {canSms && canEmail && (
            <div style={{ display: 'flex', gap: 4 }}>
              {(['sms', 'email'] as const).map(ch => (
                <button
                  key={ch}
                  onClick={() => setChannel(ch)}
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 5,
                    height: 26, padding: '0 10px', fontSize: 12, cursor: 'pointer',
                    borderRadius: 'var(--radius-pill)',
                    border: channel === ch ? '1px solid var(--color-accent)' : '1px solid var(--color-ink-200)',
                    background: channel === ch ? 'color-mix(in srgb, var(--color-accent) 10%, transparent)' : 'transparent',
                    color: channel === ch ? 'var(--color-accent)' : 'var(--color-ink-500)',
                  }}
                >
                  {ch === 'sms' ? <MessageSquare size={11} strokeWidth={1.5} /> : <Mail size={11} strokeWidth={1.5} />}
                  {ch === 'sms' ? 'Text' : 'Email'}
                </button>
              ))}
            </div>
          )}
          {channel === 'email' && (
            <input
              value={subject}
              onChange={e => setSubject(e.target.value)}
              placeholder="Subject"
              className="drawer-input"
            />
          )}
          <textarea
            value={text}
            onChange={e => setText(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }}
            placeholder={channel === 'sms' ? `Text ${lead.contact_name || 'this contact'}… (Enter to send)` : 'Write an email… (Enter to send)'}
            rows={2}
            style={TEXTAREA_STYLE}
            onFocus={e => {
              e.currentTarget.style.borderColor = 'var(--color-accent)'
              e.currentTarget.style.boxShadow = '0 0 0 3px color-mix(in srgb, var(--color-accent) 18%, transparent)'
            }}
            onBlur={e => {
              e.currentTarget.style.borderColor = 'var(--color-ink-200)'
              e.currentTarget.style.boxShadow = 'none'
            }}
          />
          <button
            onClick={handleSend}
            disabled={!text.trim() || sending}
            className="btn-primary"
            style={{ alignSelf: 'flex-end', display: 'inline-flex', alignItems: 'center', gap: 6, height: 34, padding: '0 14px', fontSize: 13, opacity: !text.trim() || sending ? 0.5 : 1 }}
          >
            {channel === 'sms' ? <MessageSquare size={13} strokeWidth={1.5} /> : <Mail size={13} strokeWidth={1.5} />}
            {sending ? 'Sending…' : 'Send'}
          </button>
        </div>
      ) : (
        <p style={{ fontSize: 12, color: 'var(--color-ink-400)', margin: 0 }}>
          Add a phone number or email to this contact to message them.
        </p>
      )}

      {/* Saved templates (server-side merge fields) */}
      {templates.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>
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
            onClick={handleSendTemplate}
            disabled={selectedId === '' || sending}
            className="btn-primary"
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 34, padding: '0 14px', fontSize: 13,
                     opacity: selectedId === '' || sending ? 0.5 : 1 }}
          >
            <Send size={13} strokeWidth={1.5} />
            Send
          </button>
        </div>
      )}
      {selected?.subject && (
        <p style={{ margin: '8px 0 0', fontSize: 12, color: 'var(--color-ink-400)' }}>Subject: {selected.subject}</p>
      )}
      {result && <p style={{ margin: '8px 0 0', fontSize: 12, color: 'var(--color-ink-500)' }}>{result}</p>}
    </section>
  )
}
