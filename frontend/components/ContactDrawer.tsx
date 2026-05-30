'use client'
import { useEffect, useState, useRef } from 'react'
import { X, Plus, Phone, DoorOpen, Mail, MessageSquare } from 'lucide-react'
import type { Lead, Note, HistoryEntry, LeadStatus } from '@/lib/types'
import { getNotes, addNote, getHistory, addHistory } from '@/lib/api'
import { StatusSelect } from './StatusSelect'
import { ScoreBadge } from './ScoreBadge'

interface Props {
  lead: Lead | null
  onClose: () => void
  onStatusChange: (id: number, s: LeadStatus) => void
}

const ACTION_OPTIONS = ['Called', 'Door knocked', 'Emailed', 'Texted', 'Left voicemail', 'Meeting']
const OUTCOME_OPTIONS = ['No answer', 'Left message', 'Not interested', 'Interested', 'Quoted', 'Booked', 'Converted']

function fmt(d: string | null) {
  if (!d) return '—'
  return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}
function fmtCurrency(n: number | null) {
  if (!n) return '—'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n)
}

export function ContactDrawer({ lead, onClose, onStatusChange }: Props) {
  const [notes, setNotes]       = useState<Note[]>([])
  const [history, setHistory]   = useState<HistoryEntry[]>([])
  const [noteText, setNoteText] = useState('')
  const [action, setAction]     = useState('Called')
  const [outcome, setOutcome]   = useState('')
  const [saving, setSaving]     = useState(false)
  const noteRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (!lead) return
    setNotes([]); setHistory([])
    getNotes(lead.id).then(setNotes).catch(() => {})
    getHistory(lead.id).then(setHistory).catch(() => {})
  }, [lead?.id])

  if (!lead) return null

  const address = [lead.address, lead.city, lead.state].filter(Boolean).join(', ')

  async function submitNote(e: React.FormEvent) {
    e.preventDefault()
    if (!noteText.trim()) return
    setSaving(true)
    try {
      const n = await addNote(lead!.id, noteText.trim())
      setNotes(prev => [n, ...prev])
      setNoteText('')
    } finally { setSaving(false) }
  }

  async function submitHistory(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    try {
      const h = await addHistory(lead!.id, action, outcome || undefined)
      setHistory(prev => [h, ...prev])
      setOutcome('')
    } finally { setSaving(false) }
  }

  const SECTION_BORDER: React.CSSProperties = { borderBottom: '1px solid var(--color-ink-100)' }

  return (
    <>
      {/* Backdrop — 32% ink per design system */}
      <div
        style={{ position: 'fixed', inset: 0, background: 'rgba(22,24,29,0.32)', zIndex: 40 }}
        onClick={onClose}
      />

      <aside
        style={{
          position: 'fixed',
          right: 0,
          top: 0,
          height: '100%',
          width: 440,
          background: 'white',
          zIndex: 50,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          boxShadow: 'var(--shadow-drawer)',
        }}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            padding: '20px 24px',
            borderBottom: '1px solid var(--color-ink-200)',
            flexShrink: 0,
          }}
        >
          <div>
            <p className="t-eyebrow" style={{ marginBottom: 4 }}>{lead.zip}</p>
            <h2
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 17,
                fontWeight: 600,
                color: 'var(--color-ink-900)',
                lineHeight: 1.2,
                margin: 0,
              }}
            >
              {address}
            </h2>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10 }}>
              <ScoreBadge grade={lead.score_grade} score={lead.lead_score} />
              <StatusSelect leadId={lead.id} value={lead.status} onChange={s => onStatusChange(lead.id, s)} />
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              padding: 6,
              borderRadius: 'var(--radius-button)',
              border: 'none',
              background: 'transparent',
              color: 'var(--color-ink-400)',
              cursor: 'pointer',
              display: 'flex',
              transition: 'background 120ms, color 120ms',
            }}
            onMouseEnter={e => {
              (e.currentTarget as HTMLButtonElement).style.background = 'var(--color-paper)'
              ;(e.currentTarget as HTMLButtonElement).style.color = 'var(--color-ink-900)'
            }}
            onMouseLeave={e => {
              (e.currentTarget as HTMLButtonElement).style.background = 'transparent'
              ;(e.currentTarget as HTMLButtonElement).style.color = 'var(--color-ink-400)'
            }}
          >
            <X size={16} strokeWidth={1.5} />
          </button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto' }}>
          {/* Property signals */}
          <section style={{ padding: '16px 24px', ...SECTION_BORDER }}>
            <p className="t-eyebrow" style={{ marginBottom: 12 }}>Property signals</p>
            <dl style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: 16, rowGap: 10 }}>
              {[
                ['Year built',     lead.year_built],
                ['Sq footage',     lead.square_footage ? `${lead.square_footage.toLocaleString()} sqft` : null],
                ['Garage spaces',  lead.garage_spaces],
                ['Est. value',     fmtCurrency(lead.estimated_value)],
                ['Est. equity',    fmtCurrency(lead.estimated_equity)],
                ['Last sale',      fmt(lead.last_sale_date)],
                ['Sale price',     fmtCurrency(lead.last_sale_price)],
                ['Area income',    fmtCurrency(lead.zip_median_income)],
                ['Permits (24mo)', lead.permit_count_24mo ?? '—'],
                ['Owner',          lead.owner_name],
              ].map(([label, val]) => (
                <div key={String(label)}>
                  <dt className="t-eyebrow" style={{ marginBottom: 2 }}>{label}</dt>
                  <dd
                    className="tabular"
                    style={{ fontWeight: 500, color: 'var(--color-ink-900)', fontSize: 13, margin: 0 }}
                  >
                    {val ?? '—'}
                  </dd>
                </div>
              ))}
            </dl>
          </section>

          {/* Log contact */}
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
            {history.length > 0 && (
              <ul style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 6, listStyle: 'none', padding: 0 }}>
                {history.map(h => (
                  <li key={h.id} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, fontSize: 12 }}>
                    <ContactIcon action={h.action} />
                    <div>
                      <span style={{ fontWeight: 500, color: 'var(--color-ink-900)' }}>{h.action}</span>
                      {h.outcome && <span style={{ color: 'var(--color-ink-500)' }}> · {h.outcome}</span>}
                      <p style={{ color: 'var(--color-ink-400)', fontSize: 11, marginTop: 2, marginBottom: 0 }}>{fmt(h.created_at)}</p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* Notes */}
          <section style={{ padding: '16px 24px' }}>
            <p className="t-eyebrow" style={{ marginBottom: 12 }}>Notes</p>
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
            {notes.length > 0 && (
              <ul style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 10, listStyle: 'none', padding: 0 }}>
                {notes.map(n => (
                  <li
                    key={n.id}
                    style={{
                      background: 'var(--color-paper)',
                      borderRadius: 'var(--radius-card)',
                      padding: '10px 14px',
                      border: '1px solid var(--color-ink-200)',
                      boxShadow: 'var(--shadow-card)',
                    }}
                  >
                    <p style={{ color: 'var(--color-ink-900)', fontSize: 13, lineHeight: 1.55, margin: 0 }}>{n.note}</p>
                    <p style={{ color: 'var(--color-ink-400)', fontSize: 11, marginTop: 6, marginBottom: 0 }}>{fmt(n.created_at)}</p>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </aside>
    </>
  )
}

function ContactIcon({ action }: { action: string }) {
  const a = action.toLowerCase()
  if (a.includes('call') || a.includes('voicemail'))
    return <Phone size={13} strokeWidth={1.5} style={{ color: 'var(--color-accent)', marginTop: 1, flexShrink: 0 }} />
  if (a.includes('door'))
    return <DoorOpen size={13} strokeWidth={1.5} style={{ color: 'var(--color-moss)', marginTop: 1, flexShrink: 0 }} />
  if (a.includes('email'))
    return <Mail size={13} strokeWidth={1.5} style={{ color: 'var(--color-warning)', marginTop: 1, flexShrink: 0 }} />
  return <MessageSquare size={13} strokeWidth={1.5} style={{ color: 'var(--color-plum)', marginTop: 1, flexShrink: 0 }} />
}
