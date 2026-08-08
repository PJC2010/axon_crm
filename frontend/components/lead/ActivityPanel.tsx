'use client'
import { useEffect, useRef, useState } from 'react'
import { Plus, Phone, DoorOpen, Mail, MessageSquare, FileText, CheckSquare, Zap, Send } from 'lucide-react'
import type { TimelineEntry } from '@/lib/types'
import { getTimeline, addNote, addHistory, sendLeadMessage } from '@/lib/api'
import { fmt } from './format'

const ACTION_OPTIONS = ['Called', 'Door knocked', 'Emailed', 'Texted', 'Left voicemail', 'Meeting']
const OUTCOME_OPTIONS = ['No answer', 'Left message', 'Not interested', 'Interested', 'Quoted', 'Booked', 'Converted']

const SECTION_BORDER: React.CSSProperties = { borderBottom: '1px solid var(--color-ink-100)' }

/** Log-contact + add-note forms, the two-way text composer, and the unified
 *  activity timeline. Self-fetching by lead id so it can be reused by the
 *  drawer and the full lead page.
 *
 *  `contactPhone` is what gates the text composer — pass the record's phone and
 *  the reply box appears under the conversation. Sends go out from the account's
 *  own tracking number when it has one, so replies come back to the same thread
 *  (api/notifications.py::account_sms_from). */
export function ActivityPanel({ leadId, contactPhone }: { leadId: number; contactPhone?: string | null }) {
  const [timeline, setTimeline] = useState<TimelineEntry[]>([])
  const [noteText, setNoteText] = useState('')
  const [action, setAction]     = useState('Called')
  const [outcome, setOutcome]   = useState('')
  const [saving, setSaving]     = useState(false)
  const [smsText, setSmsText]   = useState('')
  const [sendingSms, setSendingSms] = useState(false)
  const [smsError, setSmsError] = useState<string | null>(null)
  const noteRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    setTimeline([])
    getTimeline(leadId).then(setTimeline).catch(() => {})
  }, [leadId])

  function refreshTimeline() {
    getTimeline(leadId).then(setTimeline).catch(() => {})
  }

  async function submitSms(e: React.FormEvent) {
    e.preventDefault()
    const body = smsText.trim()
    if (!body) return
    setSendingSms(true)
    setSmsError(null)
    try {
      await sendLeadMessage(leadId, { channel: 'sms', body })
      setSmsText('')
      refreshTimeline()
    } catch (err: unknown) {
      setSmsError(err instanceof Error ? err.message : 'Text failed to send')
    } finally { setSendingSms(false) }
  }

  async function submitNote(e: React.FormEvent) {
    e.preventDefault()
    if (!noteText.trim()) return
    setSaving(true)
    try {
      await addNote(leadId, noteText.trim())
      setNoteText('')
      refreshTimeline()
    } finally { setSaving(false) }
  }

  async function submitHistory(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    try {
      await addHistory(leadId, action, outcome || undefined)
      setOutcome('')
      refreshTimeline()
    } finally { setSaving(false) }
  }

  return (
    <>
      <section style={{ padding: '16px 24px', ...SECTION_BORDER }}>
        <p className="t-eyebrow" style={{ marginBottom: 12 }}>Log contact</p>
        <form onSubmit={submitHistory} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ display: 'flex', gap: 8 }}>
            <select value={action} onChange={e => setAction(e.target.value)} className="select-field" style={{ flex: 1 }}>
              {ACTION_OPTIONS.map(a => <option key={a}>{a}</option>)}
            </select>
            <select value={outcome} onChange={e => setOutcome(e.target.value)} className="select-field" style={{ flex: 1 }}>
              <option value="">Outcome…</option>
              {OUTCOME_OPTIONS.map(o => <option key={o}>{o}</option>)}
            </select>
          </div>
          <button type="submit" disabled={saving} className="btn-primary" style={{ alignSelf: 'flex-end' }}>
            <Plus size={13} strokeWidth={1.5} /> Log
          </button>
        </form>
      </section>

      <section style={{ padding: '16px 24px', ...SECTION_BORDER }}>
        <p className="t-eyebrow" style={{ marginBottom: 12 }}>Add note</p>
        <form onSubmit={submitNote} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <textarea
            ref={noteRef}
            value={noteText}
            onChange={e => setNoteText(e.target.value)}
            placeholder="Add a note…"
            rows={2}
            style={{
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
            }}
            onFocus={e => {
              e.currentTarget.style.borderColor = 'var(--color-accent)'
              e.currentTarget.style.boxShadow = '0 0 0 3px color-mix(in srgb, var(--color-accent) 18%, transparent)'
            }}
            onBlur={e => {
              e.currentTarget.style.borderColor = 'var(--color-ink-200)'
              e.currentTarget.style.boxShadow = 'none'
            }}
          />
          <button type="submit" disabled={saving || !noteText.trim()} className="btn-primary" style={{ alignSelf: 'flex-end' }}>
            <Plus size={13} strokeWidth={1.5} /> Add note
          </button>
        </form>
      </section>

      {/* Two-way texting: type a reply straight into the thread below. */}
      {contactPhone && (
        <section style={{ padding: '16px 24px', ...SECTION_BORDER }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 }}>
            <MessageSquare size={13} strokeWidth={1.5} style={{ color: 'var(--color-accent)' }} />
            <p className="t-eyebrow" style={{ margin: 0 }}>Send a text</p>
          </div>
          <form onSubmit={submitSms} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <textarea
              value={smsText}
              onChange={e => { setSmsText(e.target.value); setSmsError(null) }}
              placeholder={`Text ${contactPhone}…`}
              rows={2}
              maxLength={1600}
              onKeyDown={e => {
                // ⌘/Ctrl+Enter sends — Enter alone keeps making new lines, since
                // a text is often more than one.
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault()
                  if (smsText.trim() && !sendingSms) submitSms(e)
                }
              }}
              style={{
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
              }}
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
              type="submit"
              disabled={sendingSms || !smsText.trim()}
              className="btn-primary"
              style={{ alignSelf: 'flex-end', display: 'inline-flex', alignItems: 'center', gap: 6 }}
            >
              <Send size={13} strokeWidth={1.5} /> {sendingSms ? 'Sending…' : 'Send text'}
            </button>
          </form>
          {smsError && (
            <p style={{ margin: '8px 0 0', fontSize: 12, color: 'var(--color-rose)' }}>{smsError}</p>
          )}
        </section>
      )}

      <section style={{ padding: '16px 24px' }}>
        <p className="t-eyebrow" style={{ marginBottom: 12 }}>Activity</p>
        {timeline.length === 0 ? (
          <p style={{ fontSize: 13, color: 'var(--color-ink-400)', margin: 0 }}>No activity yet</p>
        ) : (
          <ul style={{ display: 'flex', flexDirection: 'column', gap: 8, listStyle: 'none', padding: 0, margin: 0 }}>
            {timeline.map(entry => (
              <li key={`${entry.type}-${entry.id}`} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, fontSize: 12 }}>
                <TimelineIcon entry={entry} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  {isMessage(entry) ? (
                    <MessageBubble entry={entry} />
                  ) : (entry.type === 'history' || entry.type === 'signal') && (
                    <>
                      <span style={{ fontWeight: 500, color: 'var(--color-ink-900)' }}>{entry.title}</span>
                      {entry.detail && <span style={{ color: 'var(--color-ink-500)' }}> · {entry.detail}</span>}
                    </>
                  )}
                  {entry.type === 'note' && (
                    <p style={{
                      color: 'var(--color-ink-900)',
                      fontSize: 13,
                      lineHeight: 1.5,
                      margin: 0,
                      background: 'var(--color-paper)',
                      borderRadius: 'var(--radius-card)',
                      padding: '8px 12px',
                      border: '1px solid var(--color-ink-200)',
                    }}>
                      {entry.title}
                    </p>
                  )}
                  {entry.type === 'task' && (
                    <span style={{
                      fontWeight: 500,
                      color: entry.detail === 'completed' ? 'var(--color-ink-400)' : 'var(--color-ink-900)',
                      textDecoration: entry.detail === 'completed' ? 'line-through' : 'none',
                    }}>
                      {entry.title}
                      {entry.detail && entry.detail !== 'completed' && (
                        <span style={{
                          marginLeft: 6,
                          fontSize: 10,
                          fontWeight: 600,
                          padding: '1px 6px',
                          borderRadius: 'var(--radius-pill)',
                          background: entry.detail === 'urgent' ? 'var(--color-danger-100, #FEE2E2)' :
                                      entry.detail === 'high' ? '#FEF3C7' : 'var(--color-ink-100)',
                          color: entry.detail === 'urgent' ? 'var(--color-danger, #DC2626)' :
                                 entry.detail === 'high' ? '#92400E' : 'var(--color-ink-500)',
                          textTransform: 'uppercase',
                          letterSpacing: '0.05em',
                        }}>
                          {entry.detail}
                        </span>
                      )}
                    </span>
                  )}
                  <p style={{ color: 'var(--color-ink-400)', fontSize: 11, marginTop: 2, marginBottom: 0 }}>{fmt(entry.created_at)}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  )
}

/** History entries that are actual messages (two-way SMS / templated sends)
 *  carry channel/direction/body and render as a conversation bubble. */
function isMessage(entry: TimelineEntry): boolean {
  return entry.type === 'history' && !!entry.body && !!entry.direction
}

function MessageBubble({ entry }: { entry: TimelineEntry }) {
  const inbound = entry.direction === 'inbound'
  return (
    <div style={{ display: 'flex', justifyContent: inbound ? 'flex-start' : 'flex-end' }}>
      <div style={{ maxWidth: '85%' }}>
        <p style={{
          fontSize: 13,
          lineHeight: 1.5,
          margin: 0,
          padding: '8px 12px',
          borderRadius: 'var(--radius-card)',
          whiteSpace: 'pre-wrap',
          overflowWrap: 'break-word',
          background: inbound
            ? 'var(--color-paper)'
            : 'color-mix(in srgb, var(--color-accent) 12%, transparent)',
          border: inbound
            ? '1px solid var(--color-ink-200)'
            : '1px solid color-mix(in srgb, var(--color-accent) 25%, transparent)',
          color: 'var(--color-ink-900)',
        }}>
          {entry.body}
        </p>
        <p style={{ fontSize: 10, color: 'var(--color-ink-400)', margin: '3px 2px 0', textAlign: inbound ? 'left' : 'right', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
          {entry.channel === 'sms' ? (inbound ? 'Text received' : 'Text sent') : (inbound ? 'Email received' : 'Email sent')}
        </p>
      </div>
    </div>
  )
}

function TimelineIcon({ entry }: { entry: TimelineEntry }) {
  const iconStyle = { marginTop: 1, flexShrink: 0 } as const
  if (entry.type === 'note')
    return <FileText size={13} strokeWidth={1.5} style={{ ...iconStyle, color: 'var(--color-plum)' }} />
  if (entry.type === 'task')
    return <CheckSquare size={13} strokeWidth={1.5} style={{ ...iconStyle, color: entry.detail === 'completed' ? 'var(--color-moss)' : 'var(--color-warning)' }} />
  if (entry.type === 'signal')
    return <Zap size={13} strokeWidth={1.5} style={{ ...iconStyle, color: 'var(--color-gold, #B8860B)' }} />
  const a = entry.title.toLowerCase()
  if (a.includes('call') || a.includes('voicemail'))
    return <Phone size={13} strokeWidth={1.5} style={{ ...iconStyle, color: 'var(--color-accent)' }} />
  if (a.includes('door'))
    return <DoorOpen size={13} strokeWidth={1.5} style={{ ...iconStyle, color: 'var(--color-moss)' }} />
  if (a.includes('email'))
    return <Mail size={13} strokeWidth={1.5} style={{ ...iconStyle, color: 'var(--color-warning)' }} />
  return <MessageSquare size={13} strokeWidth={1.5} style={{ ...iconStyle, color: 'var(--color-plum)' }} />
}
