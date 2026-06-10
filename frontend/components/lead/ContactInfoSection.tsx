'use client'
import { useEffect, useState } from 'react'
import { Phone, Mail, Pencil, Check, User, Sparkles, MapPin, Clock, Smartphone, AtSign, MessageCircle } from 'lucide-react'
import type { Lead } from '@/lib/types'
import { updateLeadContact, enrichLead, type ContactUpdate } from '@/lib/api'

const SECTION_BORDER: React.CSSProperties = { borderBottom: '1px solid var(--color-ink-100)' }

const INPUT_STYLE: React.CSSProperties = {
  flex: 1,
  fontSize: 13,
  padding: '6px 10px',
  borderRadius: 'var(--radius-input)',
  border: '1px solid var(--color-ink-200)',
  background: 'var(--color-paper)',
  color: 'var(--color-ink-900)',
  fontFamily: 'var(--font-sans)',
  outline: 'none',
}

// All editable text fields, in display order. preferred_contact_method is a
// select and handled separately.
const TEXT_FIELDS: { label: string; key: keyof ContactUpdate; placeholder: string; type: string }[] = [
  { label: 'Name',     key: 'contact_name',      placeholder: 'Contact name',         type: 'text'  },
  { label: 'Phone',    key: 'contact_phone',     placeholder: '(555) 123-4567',       type: 'tel'   },
  { label: 'Email',    key: 'contact_email',     placeholder: 'name@example.com',     type: 'email' },
  { label: 'Phone 2',  key: 'contact_phone_alt', placeholder: 'Secondary phone',      type: 'tel'   },
  { label: 'Email 2',  key: 'contact_email_alt', placeholder: 'Alternate email',      type: 'email' },
  { label: 'Mailing',  key: 'mailing_address',   placeholder: 'Mailing address',      type: 'text'  },
  { label: 'Best time', key: 'best_time_to_call', placeholder: 'e.g. Weekdays after 5pm', type: 'text' },
]

const METHOD_OPTIONS = ['phone', 'text', 'email']

type Draft = Record<keyof ContactUpdate, string>

function draftFrom(lead: Lead): Draft {
  return {
    contact_name:             lead.contact_name ?? '',
    contact_phone:            lead.contact_phone ?? '',
    contact_email:            lead.contact_email ?? '',
    contact_phone_alt:        lead.contact_phone_alt ?? '',
    contact_email_alt:        lead.contact_email_alt ?? '',
    mailing_address:          lead.mailing_address ?? '',
    preferred_contact_method: lead.preferred_contact_method ?? '',
    best_time_to_call:        lead.best_time_to_call ?? '',
  }
}

interface Props {
  lead: Lead
  onSaved: (lead: Lead) => void
  onToast?: (message: string, variant?: 'success' | 'error') => void
}

/** Contact-info block: read view, inline edit of all contact fields, and an
 *  on-demand skip-trace "Enrich" button. Shared by the drawer and lead page. */
export function ContactInfoSection({ lead, onSaved, onToast }: Props) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<Draft>(() => draftFrom(lead))
  const [saving, setSaving] = useState(false)
  const [enriching, setEnriching] = useState(false)

  // Reset the draft and leave edit mode whenever a different lead is shown.
  useEffect(() => {
    setDraft(draftFrom(lead))
    setEditing(false)
  }, [lead.id])

  async function save() {
    setSaving(true)
    try {
      const body: ContactUpdate = {}
      for (const key of Object.keys(draft) as (keyof ContactUpdate)[]) {
        const current = (lead[key as keyof Lead] as string | null) ?? ''
        if (draft[key] !== current) body[key] = draft[key]
      }
      if (Object.keys(body).length > 0) {
        const updated = await updateLeadContact(lead.id, body)
        onSaved(updated)
      }
      setEditing(false)
    } catch (e) {
      onToast?.(e instanceof Error ? e.message : 'Failed to save contact', 'error')
    } finally { setSaving(false) }
  }

  async function enrich() {
    setEnriching(true)
    try {
      const updated = await enrichLead(lead.id)
      onSaved(updated)
      onToast?.('Contact details enriched', 'success')
    } catch (e) {
      onToast?.(e instanceof Error ? e.message : 'Enrichment failed', 'error')
    } finally { setEnriching(false) }
  }

  return (
    <section style={{ padding: '16px 24px', ...SECTION_BORDER }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <p className="t-eyebrow" style={{ margin: 0 }}>Contact info</p>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <button
            onClick={enrich}
            disabled={enriching}
            className="dash-icon-btn borderless"
            title="Skip-trace this lead for more contact details"
            style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: 'var(--color-ink-400)' }}
          >
            <Sparkles size={12} strokeWidth={1.5} className={enriching ? 'animate-spin' : ''} />
            {enriching ? 'Enriching…' : 'Enrich'}
          </button>
          {editing ? (
            <button
              onClick={save}
              disabled={saving}
              className="dash-icon-btn borderless"
              style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: 'var(--color-accent)' }}
            >
              <Check size={13} strokeWidth={1.5} /> Save
            </button>
          ) : (
            <button
              onClick={() => setEditing(true)}
              className="dash-icon-btn borderless"
              style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: 'var(--color-ink-400)' }}
            >
              <Pencil size={11} strokeWidth={1.5} /> Edit
            </button>
          )}
        </div>
      </div>

      {editing ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {TEXT_FIELDS.map(({ label, key, placeholder, type }) => (
            <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <label className="t-eyebrow" style={{ width: 64, margin: 0 }}>{label}</label>
              <input
                type={type}
                value={draft[key]}
                onChange={e => setDraft(prev => ({ ...prev, [key]: e.target.value }))}
                placeholder={placeholder}
                style={INPUT_STYLE}
                onKeyDown={e => { if (e.key === 'Enter') save() }}
              />
            </div>
          ))}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <label className="t-eyebrow" style={{ width: 64, margin: 0 }}>Prefers</label>
            <select
              value={draft.preferred_contact_method}
              onChange={e => setDraft(prev => ({ ...prev, preferred_contact_method: e.target.value }))}
              className="select-field"
              style={{ flex: 1 }}
            >
              <option value="">No preference</option>
              {METHOD_OPTIONS.map(m => <option key={m} value={m}>{m[0].toUpperCase() + m.slice(1)}</option>)}
            </select>
          </div>
        </div>
      ) : (
        <ReadView lead={lead} />
      )}
    </section>
  )
}

function Row({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span style={{ color: 'var(--color-ink-400)', flexShrink: 0, display: 'flex' }}>{icon}</span>
      {children}
    </div>
  )
}

function LinkOrDash({ href, text }: { href: string; text: string | null }) {
  if (!text) return <dd style={{ fontSize: 13, color: 'var(--color-ink-400)', margin: 0 }}>—</dd>
  return (
    <a href={href} style={{ fontSize: 13, color: 'var(--color-accent)', textDecoration: 'none' }}>{text}</a>
  )
}

function ReadView({ lead }: { lead: Lead }) {
  const method = lead.preferred_contact_method
  return (
    <dl style={{ display: 'flex', flexDirection: 'column', gap: 8, margin: 0 }}>
      <Row icon={<User size={13} strokeWidth={1.5} />}>
        <dd style={{ fontSize: 13, fontWeight: 500, color: 'var(--color-ink-900)', margin: 0 }}>
          {lead.contact_name || lead.owner_name || '—'}
        </dd>
      </Row>
      <Row icon={<Phone size={13} strokeWidth={1.5} />}>
        <LinkOrDash href={`tel:${lead.contact_phone}`} text={lead.contact_phone} />
      </Row>
      <Row icon={<Mail size={13} strokeWidth={1.5} />}>
        <LinkOrDash href={`mailto:${lead.contact_email}`} text={lead.contact_email} />
      </Row>

      {/* Extended fields — only shown when present, to keep the read view tidy. */}
      {lead.contact_phone_alt && (
        <Row icon={<Smartphone size={13} strokeWidth={1.5} />}>
          <LinkOrDash href={`tel:${lead.contact_phone_alt}`} text={lead.contact_phone_alt} />
        </Row>
      )}
      {lead.contact_email_alt && (
        <Row icon={<AtSign size={13} strokeWidth={1.5} />}>
          <LinkOrDash href={`mailto:${lead.contact_email_alt}`} text={lead.contact_email_alt} />
        </Row>
      )}
      {lead.mailing_address && (
        <Row icon={<MapPin size={13} strokeWidth={1.5} />}>
          <dd style={{ fontSize: 13, color: 'var(--color-ink-900)', margin: 0 }}>{lead.mailing_address}</dd>
        </Row>
      )}
      {lead.best_time_to_call && (
        <Row icon={<Clock size={13} strokeWidth={1.5} />}>
          <dd style={{ fontSize: 13, color: 'var(--color-ink-900)', margin: 0 }}>{lead.best_time_to_call}</dd>
        </Row>
      )}
      {method && (
        <Row icon={<MessageCircle size={13} strokeWidth={1.5} />}>
          <dd style={{ fontSize: 13, color: 'var(--color-ink-900)', margin: 0 }}>
            Prefers {method}
          </dd>
        </Row>
      )}
    </dl>
  )
}
