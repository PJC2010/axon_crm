'use client'
import { SkipForward } from 'lucide-react'
import { ScoreBadge } from '@/components/ds'
import { fmtPhone } from './DialerLeadCard'
import type { CallDisposition, DialerQueueItem } from '@/lib/types'

const LAST_LABEL: Record<CallDisposition, string> = {
  no_answer: 'No answer', voicemail: 'Voicemail', interested: 'Interested',
  not_interested: 'Not interested', callback: 'Callback', wrong_number: 'Wrong number',
  do_not_call: 'DNC',
}

interface Props {
  items: DialerQueueItem[]
  currentIdx: number
  skipped: Set<number>
  onJump: (idx: number) => void
}

/**
 * The rest of the session at a glance: grades, names, numbers, and how the
 * last dial went. Click a row to jump the dialer to it out of order.
 */
export function QueueList({ items, currentIdx, skipped, onJump }: Props) {
  return (
    <div style={{
      background: 'var(--color-surface)', border: '1px solid var(--color-ink-200)',
      borderRadius: 'var(--radius-card)', overflow: 'hidden',
    }}>
      <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--color-ink-200)', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-ink-400)' }}>
        Up next
      </div>
      <div style={{ maxHeight: 420, overflowY: 'auto' }}>
        {items.map((lead, idx) => {
          const active = idx === currentIdx
          const wasSkipped = skipped.has(lead.id)
          return (
            <button
              key={lead.id}
              onClick={() => onJump(idx)}
              style={{
                display: 'flex', alignItems: 'center', gap: 10, width: '100%',
                padding: '9px 14px', cursor: 'pointer', textAlign: 'left',
                border: 'none', borderBottom: '1px solid var(--color-ink-100, rgba(0,0,0,0.04))',
                background: active ? 'var(--color-surface-hi)' : 'transparent',
                opacity: wasSkipped && !active ? 0.45 : 1,
              }}
            >
              <ScoreBadge grade={lead.score_grade} />
              <span style={{ minWidth: 0, flex: 1 }}>
                <span style={{ display: 'block', fontSize: 13, fontWeight: active ? 600 : 500, color: 'var(--color-ink-900)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {lead.contact_name || lead.owner_name || lead.address || 'Unknown'}
                </span>
                <span className="tabular" style={{ display: 'block', fontSize: 11.5, color: 'var(--color-ink-400)' }}>
                  {fmtPhone(lead.contact_phone)}
                  {lead.last_disposition && ` · last: ${LAST_LABEL[lead.last_disposition]}`}
                </span>
              </span>
              {wasSkipped && <SkipForward size={12} strokeWidth={1.5} style={{ color: 'var(--color-ink-400)', flexShrink: 0 }} />}
            </button>
          )
        })}
        {items.length === 0 && (
          <p style={{ padding: '14px', fontSize: 13, color: 'var(--color-ink-400)', margin: 0 }}>
            Queue is empty.
          </p>
        )}
      </div>
    </div>
  )
}
