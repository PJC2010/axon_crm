'use client'
import { useState } from 'react'
import { Ban, CalendarClock, PhoneMissed, ThumbsDown, ThumbsUp, UserX, Voicemail } from 'lucide-react'
import type { CallDisposition } from '@/lib/types'

const OPTIONS: { d: CallDisposition; label: string; icon: React.ReactNode; tone?: 'good' | 'bad' }[] = [
  { d: 'no_answer',      label: 'No answer',      icon: <PhoneMissed size={13} strokeWidth={1.5} /> },
  { d: 'voicemail',      label: 'Left voicemail', icon: <Voicemail size={13} strokeWidth={1.5} /> },
  { d: 'interested',     label: 'Interested',     icon: <ThumbsUp size={13} strokeWidth={1.5} />, tone: 'good' },
  { d: 'callback',       label: 'Callback',       icon: <CalendarClock size={13} strokeWidth={1.5} />, tone: 'good' },
  { d: 'not_interested', label: 'Not interested', icon: <ThumbsDown size={13} strokeWidth={1.5} />, tone: 'bad' },
  { d: 'wrong_number',   label: 'Wrong number',   icon: <UserX size={13} strokeWidth={1.5} /> },
  { d: 'do_not_call',    label: 'Do not call',    icon: <Ban size={13} strokeWidth={1.5} />, tone: 'bad' },
]

function tomorrowISO(): string {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  return d.toISOString().slice(0, 10)
}

interface Props {
  disabled: boolean
  notes: string
  onNotes: (v: string) => void
  /** callbackDate only accompanies the 'callback' disposition. */
  onSubmit: (d: CallDisposition, callbackDate?: string) => void
}

/**
 * The after-call verdict row. One click logs the outcome (and auto-advances,
 * if enabled) — 'callback' first asks for a date, 'do_not_call' is confirmed
 * by the page before submitting.
 */
export function DispositionBar({ disabled, notes, onNotes, onSubmit }: Props) {
  const [callbackDate, setCallbackDate] = useState<string | null>(null)

  const toneColor = (tone?: 'good' | 'bad') =>
    tone === 'good' ? 'var(--color-moss)' : tone === 'bad' ? 'var(--color-danger)' : 'var(--color-ink-700)'

  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-ink-400)', marginBottom: 8 }}>
        How did it go?
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {OPTIONS.map(({ d, label, icon, tone }) => (
          <button
            key={d}
            disabled={disabled}
            onClick={() => {
              if (d === 'callback') { setCallbackDate(prev => prev === null ? tomorrowISO() : prev); return }
              onSubmit(d)
            }}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '7px 12px', fontSize: 12.5, fontWeight: 600,
              cursor: disabled ? 'default' : 'pointer', opacity: disabled ? 0.5 : 1,
              borderRadius: 'var(--radius-button)',
              border: `1px solid ${d === 'callback' && callbackDate !== null ? 'var(--color-accent)' : 'var(--color-ink-200)'}`,
              background: 'var(--color-surface)', color: toneColor(tone),
            }}
          >
            {icon} {label}
          </button>
        ))}
      </div>

      {callbackDate !== null && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10 }}>
          <label style={{ fontSize: 12, color: 'var(--color-ink-600)' }}>Call back on</label>
          <input
            type="date"
            value={callbackDate}
            min={new Date().toISOString().slice(0, 10)}
            onChange={e => setCallbackDate(e.target.value)}
            className="drawer-input"
            style={{ width: 150 }}
          />
          <button
            disabled={disabled || !callbackDate}
            onClick={() => { onSubmit('callback', callbackDate); setCallbackDate(null) }}
            className="btn-primary"
            style={{ fontSize: 12.5, padding: '7px 14px' }}
          >
            Schedule callback
          </button>
          <button
            onClick={() => setCallbackDate(null)}
            className="dash-icon-btn borderless"
            style={{ fontSize: 12 }}
          >
            Cancel
          </button>
        </div>
      )}

      <textarea
        value={notes}
        onChange={e => onNotes(e.target.value)}
        placeholder="Notes from the call (saved with the outcome)…"
        rows={2}
        style={{
          width: '100%', marginTop: 10, padding: '8px 10px', fontSize: 13,
          fontFamily: 'var(--font-sans)', color: 'var(--color-ink-900)',
          background: 'var(--color-surface)', border: '1px solid var(--color-ink-200)',
          borderRadius: 'var(--radius-button)', resize: 'vertical',
        }}
      />
    </div>
  )
}
