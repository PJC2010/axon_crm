'use client'
import { useEffect, useState, useRef } from 'react'
import { X, Plus, Phone, DoorOpen, Mail, MessageSquare, Pencil, Check, User, FileText, CheckSquare, Archive } from 'lucide-react'
import type { Lead, Note, HistoryEntry, LeadStatus, TimelineEntry, ScoreExplanation } from '@/lib/types'
import { getNotes, addNote, getHistory, addHistory, updateLeadContact, getTimeline, getScoreExplanation, archiveLead } from '@/lib/api'
import { StatusSelect } from './StatusSelect'
import { ScoreBadge } from './ScoreBadge'

interface Props {
  lead: Lead | null
  onClose: () => void
  onStatusChange: (id: number, s: LeadStatus) => void
}

const ACTION_OPTIONS = ['Called', 'Door knocked', 'Emailed', 'Texted', 'Left voicemail', 'Meeting']
const OUTCOME_OPTIONS = ['No answer', 'Left message', 'Not interested', 'Interested', 'Quoted', 'Booked', 'Converted']

const VERTICAL_LABELS: Record<string, string> = {
  epoxy_flooring:   'Epoxy flooring',
  pool_maintenance: 'Pool maintenance',
  solar:            'Solar',
}

function fmt(d: string | null) {
  if (!d) return '—'
  return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}
function fmtCurrency(n: number | null) {
  if (!n) return '—'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n)
}
function fmtOccupied(v: boolean | null) {
  if (v === null || v === undefined) return '—'
  return v ? 'Yes' : 'No'
}

export function ContactDrawer({ lead, onClose, onStatusChange }: Props) {
  const [timeline, setTimeline]   = useState<TimelineEntry[]>([])
  const [explanation, setExplanation] = useState<ScoreExplanation | null>(null)
  const [noteText, setNoteText] = useState('')
  const [action, setAction]     = useState('Called')
  const [outcome, setOutcome]   = useState('')
  const [saving, setSaving]     = useState(false)
  const noteRef = useRef<HTMLTextAreaElement>(null)

  const [editingContact, setEditingContact] = useState(false)
  const [contactDraft, setContactDraft] = useState({ name: '', phone: '', email: '' })
  const [savingContact, setSavingContact] = useState(false)
  const [archiving, setArchiving] = useState(false)

  useEffect(() => {
    if (!lead) return
    setTimeline([])
    setExplanation(null)
    setEditingContact(false)
    setContactDraft({
      name: lead.contact_name ?? '',
      phone: lead.contact_phone ?? '',
      email: lead.contact_email ?? '',
    })
    getTimeline(lead.id).then(setTimeline).catch(() => {})
    getScoreExplanation(lead.id).then(setExplanation).catch(() => {})
  }, [lead?.id])

  if (!lead) return null

  const address = [lead.address, lead.city, lead.state].filter(Boolean).join(', ')

  async function saveContact() {
    setSavingContact(true)
    try {
      const body: Record<string, string> = {}
      if (contactDraft.name !== (lead!.contact_name ?? '')) body.contact_name = contactDraft.name
      if (contactDraft.phone !== (lead!.contact_phone ?? '')) body.contact_phone = contactDraft.phone
      if (contactDraft.email !== (lead!.contact_email ?? '')) body.contact_email = contactDraft.email
      if (Object.keys(body).length > 0) await updateLeadContact(lead!.id, body)
      setEditingContact(false)
    } finally { setSavingContact(false) }
  }

  async function refreshTimeline() {
    getTimeline(lead!.id).then(setTimeline).catch(() => {})
  }

  async function submitNote(e: React.FormEvent) {
    e.preventDefault()
    if (!noteText.trim()) return
    setSaving(true)
    try {
      await addNote(lead!.id, noteText.trim())
      setNoteText('')
      refreshTimeline()
    } finally { setSaving(false) }
  }

  async function submitHistory(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    try {
      await addHistory(lead!.id, action, outcome || undefined)
      setOutcome('')
      refreshTimeline()
    } finally { setSaving(false) }
  }

  async function handleArchive() {
    if (!lead) return
    setArchiving(true)
    try {
      await archiveLead(lead.id)
      onClose()
    } finally { setArchiving(false) }
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
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={handleArchive}
              disabled={archiving}
              className="dash-icon-btn borderless"
              title="Archive this lead"
            >
              <Archive size={16} strokeWidth={1.5} />
            </button>
            <button onClick={onClose} className="dash-icon-btn borderless">
              <X size={16} strokeWidth={1.5} />
            </button>
          </div>
        </div>

        <div style={{ flex: 1, overflowY: 'auto' }}>
          {/* Contact info */}
          <section style={{ padding: '16px 24px', ...SECTION_BORDER }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <p className="t-eyebrow" style={{ margin: 0 }}>Contact info</p>
              {editingContact ? (
                <button
                  onClick={saveContact}
                  disabled={savingContact}
                  className="dash-icon-btn borderless"
                  style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: 'var(--color-accent)' }}
                >
                  <Check size={13} strokeWidth={1.5} /> Save
                </button>
              ) : (
                <button
                  onClick={() => setEditingContact(true)}
                  className="dash-icon-btn borderless"
                  style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: 'var(--color-ink-400)' }}
                >
                  <Pencil size={11} strokeWidth={1.5} /> Edit
                </button>
              )}
            </div>
            {editingContact ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {[
                  { label: 'Name', key: 'name' as const, placeholder: 'Contact name' },
                  { label: 'Phone', key: 'phone' as const, placeholder: '(555) 123-4567' },
                  { label: 'Email', key: 'email' as const, placeholder: 'name@example.com' },
                ].map(({ label, key, placeholder }) => (
                  <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <label className="t-eyebrow" style={{ width: 48, margin: 0 }}>{label}</label>
                    <input
                      type={key === 'email' ? 'email' : key === 'phone' ? 'tel' : 'text'}
                      value={contactDraft[key]}
                      onChange={e => setContactDraft(prev => ({ ...prev, [key]: e.target.value }))}
                      placeholder={placeholder}
                      style={{
                        flex: 1,
                        fontSize: 13,
                        padding: '6px 10px',
                        borderRadius: 'var(--radius-input)',
                        border: '1px solid var(--color-ink-200)',
                        background: 'var(--color-paper)',
                        color: 'var(--color-ink-900)',
                        fontFamily: 'var(--font-sans)',
                        outline: 'none',
                      }}
                      onKeyDown={e => { if (e.key === 'Enter') saveContact() }}
                    />
                  </div>
                ))}
              </div>
            ) : (
              <dl style={{ display: 'flex', flexDirection: 'column', gap: 8, margin: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <User size={13} strokeWidth={1.5} style={{ color: 'var(--color-ink-400)', flexShrink: 0 }} />
                  <dd style={{ fontSize: 13, fontWeight: 500, color: 'var(--color-ink-900)', margin: 0 }}>
                    {lead.contact_name || lead.owner_name || '—'}
                  </dd>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Phone size={13} strokeWidth={1.5} style={{ color: 'var(--color-ink-400)', flexShrink: 0 }} />
                  {lead.contact_phone ? (
                    <a href={`tel:${lead.contact_phone}`} style={{ fontSize: 13, color: 'var(--color-accent)', textDecoration: 'none' }}>
                      {lead.contact_phone}
                    </a>
                  ) : (
                    <dd style={{ fontSize: 13, color: 'var(--color-ink-400)', margin: 0 }}>—</dd>
                  )}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Mail size={13} strokeWidth={1.5} style={{ color: 'var(--color-ink-400)', flexShrink: 0 }} />
                  {lead.contact_email ? (
                    <a href={`mailto:${lead.contact_email}`} style={{ fontSize: 13, color: 'var(--color-accent)', textDecoration: 'none' }}>
                      {lead.contact_email}
                    </a>
                  ) : (
                    <dd style={{ fontSize: 13, color: 'var(--color-ink-400)', margin: 0 }}>—</dd>
                  )}
                </div>
              </dl>
            )}
          </section>

          {/* Property signals */}
          <section style={{ padding: '16px 24px', ...SECTION_BORDER }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <p className="t-eyebrow" style={{ margin: 0 }}>Property signals</p>
              {lead.vertical && (
                <span style={{
                  fontSize: 10,
                  fontWeight: 600,
                  padding: '2px 8px',
                  borderRadius: 'var(--radius-pill)',
                  background: 'var(--color-accent-100)',
                  color: 'var(--color-accent-800)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                }}>
                  {VERTICAL_LABELS[lead.vertical] ?? lead.vertical}
                </span>
              )}
            </div>
            <dl style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: 16, rowGap: 10 }}>
              {[
                ['Year built',     lead.year_built],
                ['Sq footage',     lead.square_footage ? `${lead.square_footage.toLocaleString()} sqft` : null],
                ['Garage spaces',  lead.garage_spaces],
                ['Owner occupied', fmtOccupied(lead.owner_occupied)],
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
            {lead.score_updated_at && (
              <p style={{ marginTop: 12, marginBottom: 0, fontSize: 11, color: 'var(--color-ink-400)' }}>
                Score updated {fmt(lead.score_updated_at)}
              </p>
            )}
          </section>

          {/* Why this score — per-factor breakdown + vertical weighting */}
          <WhyThisScore explanation={explanation} />

          {/* Activity — log contact + add note forms, then unified timeline */}
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

          {/* Unified activity timeline */}
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
                      {entry.type === 'history' && (
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
        </div>
      </aside>
    </>
  )
}

function WhyThisScore({ explanation }: { explanation: ScoreExplanation | null }) {
  if (!explanation || explanation.factors.length === 0) return null
  const { factors, top_drivers, vertical, vertical_description, is_default_profile, weights_drift } = explanation

  const profileName = is_default_profile
    ? 'Default scoring profile'
    : (vertical ? (VERTICAL_LABELS[vertical] ?? vertical) : 'Scoring profile')
  const topWeights = vertical_description
    .slice(0, 3)
    .map(f => `${f.label} ${Math.round(f.weight * 100)}%`)
    .join(' · ')
  const maxContribution = Math.max(...factors.map(f => f.contribution), 1)

  return (
    <section style={{ padding: '16px 24px', borderBottom: '1px solid var(--color-ink-100)' }}>
      <p className="t-eyebrow" style={{ marginBottom: 8 }}>Why this score</p>

      {/* Auto-generated description of what this vertical weighs */}
      <p style={{ fontSize: 12, color: 'var(--color-ink-500)', lineHeight: 1.5, margin: '0 0 14px' }}>
        <span style={{ fontWeight: 600, color: 'var(--color-ink-700)' }}>{profileName}</span>
        {topWeights && <> weighs {topWeights}.</>}
      </p>

      {/* Per-factor breakdown — bar width ∝ point contribution */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {factors.map(f => {
          const isTop = top_drivers.includes(f.key)
          return (
            <div key={f.key} title={f.description}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 3 }}>
                <span style={{ fontSize: 12, fontWeight: isTop ? 600 : 500, color: isTop ? 'var(--color-ink-900)' : 'var(--color-ink-600)' }}>
                  {f.label}
                  {isTop && (
                    <span style={{
                      marginLeft: 6, fontSize: 9, fontWeight: 600, padding: '1px 6px',
                      borderRadius: 'var(--radius-pill)', background: 'var(--color-accent-100)',
                      color: 'var(--color-accent-800)', textTransform: 'uppercase', letterSpacing: '0.05em',
                    }}>Top driver</span>
                  )}
                </span>
                <span className="tabular" style={{ fontSize: 11, color: 'var(--color-ink-400)', flexShrink: 0, marginLeft: 8 }}>
                  +{f.contribution.toFixed(1)} pts · {Math.round(f.weight * 100)}%
                </span>
              </div>
              <div style={{ height: 6, borderRadius: 'var(--radius-pill)', background: 'var(--color-ink-100)', overflow: 'hidden' }}>
                <div style={{
                  height: '100%',
                  width: `${(f.contribution / maxContribution) * 100}%`,
                  background: isTop ? 'var(--color-accent)' : 'var(--color-ink-300)',
                  borderRadius: 'var(--radius-pill)',
                }} />
              </div>
            </div>
          )
        })}
      </div>

      {weights_drift && (
        <p style={{ marginTop: 12, marginBottom: 0, fontSize: 11, color: 'var(--color-warning, #B07A2A)' }}>
          Scoring weights changed since this lead was last scored — re-score for an exact match.
        </p>
      )}
    </section>
  )
}

function TimelineIcon({ entry }: { entry: TimelineEntry }) {
  const iconStyle = { marginTop: 1, flexShrink: 0 } as const
  if (entry.type === 'note')
    return <FileText size={13} strokeWidth={1.5} style={{ ...iconStyle, color: 'var(--color-plum)' }} />
  if (entry.type === 'task')
    return <CheckSquare size={13} strokeWidth={1.5} style={{ ...iconStyle, color: entry.detail === 'completed' ? 'var(--color-moss)' : 'var(--color-warning)' }} />
  const a = entry.title.toLowerCase()
  if (a.includes('call') || a.includes('voicemail'))
    return <Phone size={13} strokeWidth={1.5} style={{ ...iconStyle, color: 'var(--color-accent)' }} />
  if (a.includes('door'))
    return <DoorOpen size={13} strokeWidth={1.5} style={{ ...iconStyle, color: 'var(--color-moss)' }} />
  if (a.includes('email'))
    return <Mail size={13} strokeWidth={1.5} style={{ ...iconStyle, color: 'var(--color-warning)' }} />
  return <MessageSquare size={13} strokeWidth={1.5} style={{ ...iconStyle, color: 'var(--color-plum)' }} />
}
