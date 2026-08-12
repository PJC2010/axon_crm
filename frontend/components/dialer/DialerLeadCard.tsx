'use client'
import Link from 'next/link'
import { Clock, ExternalLink, MapPin, MessageSquare, Phone, Smartphone, User } from 'lucide-react'
import { ScoreBadge, StatusPill } from '@/components/ds'
import type { DialerQueueItem } from '@/lib/types'

export function fmtPhone(raw: string | null): string {
  const digits = (raw || '').replace(/\D/g, '').slice(-10)
  if (digits.length === 10) return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`
  return raw || '—'
}

interface Props {
  lead: DialerQueueItem
  /** Which number the next dial will use; primary unless the alt is chosen. */
  phoneChoice: 'primary' | 'alt'
  onPhoneChoice: (c: 'primary' | 'alt') => void
}

/**
 * The lead currently up in the dialer: who they are, why they graded the way
 * they did (ScoreBadge), and which number the Call button will dial. Deep-links
 * to the full lead page for anything beyond call-time context.
 */
export function DialerLeadCard({ lead, phoneChoice, onPhoneChoice }: Props) {
  const name = lead.contact_name || lead.owner_name || 'Unknown contact'
  const place = [lead.address, lead.city, lead.zip].filter(Boolean).join(', ')

  const numberRow = (choice: 'primary' | 'alt', icon: React.ReactNode, value: string | null) => {
    if (!value) return null
    const active = phoneChoice === choice
    return (
      <button
        onClick={() => onPhoneChoice(choice)}
        title={active ? 'This number will be dialed' : 'Dial this number instead'}
        style={{
          display: 'flex', alignItems: 'center', gap: 8, width: '100%',
          padding: '6px 10px', cursor: 'pointer', textAlign: 'left',
          borderRadius: 'var(--radius-button)', fontSize: 14,
          border: `1px solid ${active ? 'var(--color-accent)' : 'var(--color-ink-200)'}`,
          background: active ? 'var(--color-accent-100, var(--color-surface-hi))' : 'transparent',
          color: 'var(--color-ink-900)', fontVariantNumeric: 'tabular-nums',
        }}
      >
        {icon}
        <span style={{ fontWeight: active ? 600 : 400 }}>{fmtPhone(value)}</span>
        {active && (
          <span style={{ marginLeft: 'auto', fontSize: 10, fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase', color: 'var(--color-ink-400)' }}>
            dialing
          </span>
        )}
      </button>
    )
  }

  return (
    <div style={{
      background: 'var(--color-surface)', border: '1px solid var(--color-ink-200)',
      borderRadius: 'var(--radius-card)', padding: '18px 20px',
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <User size={15} strokeWidth={1.5} style={{ color: 'var(--color-ink-400)', flexShrink: 0 }} />
            <span style={{ fontFamily: 'var(--font-display)', fontSize: 17, fontWeight: 600, color: 'var(--color-ink-900)' }}>
              {name}
            </span>
            <Link
              href={`/leads/${lead.id}`}
              target="_blank"
              title="Open the full record in a new tab"
              style={{ display: 'inline-flex', color: 'var(--color-ink-400)' }}
            >
              <ExternalLink size={13} strokeWidth={1.5} />
            </Link>
          </div>
          {place && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6, fontSize: 13, color: 'var(--color-ink-600)' }}>
              <MapPin size={13} strokeWidth={1.5} style={{ color: 'var(--color-ink-400)', flexShrink: 0 }} />
              {place}
            </div>
          )}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6, flexShrink: 0 }}>
          <ScoreBadge grade={lead.score_grade} score={lead.lead_score} />
          <StatusPill status={lead.status} />
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 14 }}>
        {numberRow('primary', <Phone size={13} strokeWidth={1.5} style={{ color: 'var(--color-ink-400)', flexShrink: 0 }} />, lead.contact_phone)}
        {numberRow('alt', <Smartphone size={13} strokeWidth={1.5} style={{ color: 'var(--color-ink-400)', flexShrink: 0 }} />, lead.contact_phone_alt)}
      </div>

      {(lead.best_time_to_call || lead.preferred_contact_method) && (
        <div style={{ display: 'flex', gap: 16, marginTop: 12, fontSize: 12, color: 'var(--color-ink-600)', flexWrap: 'wrap' }}>
          {lead.best_time_to_call && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <Clock size={12} strokeWidth={1.5} style={{ color: 'var(--color-ink-400)' }} />
              Best time: {lead.best_time_to_call}
            </span>
          )}
          {lead.preferred_contact_method && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <MessageSquare size={12} strokeWidth={1.5} style={{ color: 'var(--color-ink-400)' }} />
              Prefers {lead.preferred_contact_method}
            </span>
          )}
        </div>
      )}
    </div>
  )
}
