'use client'
import { Mic, MicOff, Phone, PhoneOff } from 'lucide-react'
import { Button } from '@/components/ds'
import type { DialerCallState } from '@/hooks/useTwilioDevice'

function fmtElapsed(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

const STATE_LABEL: Record<DialerCallState, string> = {
  idle: '',
  connecting: 'Connecting…',
  ringing: 'Ringing…',
  'in-call': 'On call',
  ended: 'Call ended',
}

interface Props {
  /** Browser calling available (server has the TwiML App config)? */
  voiceDialing: boolean
  state: DialerCallState
  muted: boolean
  elapsedSec: number
  /** The number a tel: fallback link should dial (raw, as stored). */
  telHref: string | null
  onCall: () => void
  onHangup: () => void
  onToggleMute: () => void
}

/**
 * Call / hang-up / mute row. In browser mode the Call button drives the
 * Twilio Device; without the server-side config it renders the same button as
 * a tel: link (phone apps handle the call, dispositions are logged manually).
 */
export function CallControls({
  voiceDialing, state, muted, elapsedSec, telHref, onCall, onHangup, onToggleMute,
}: Props) {
  const inCall = state === 'connecting' || state === 'ringing' || state === 'in-call'

  if (!voiceDialing) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <a
          href={telHref ? `tel:${telHref}` : undefined}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 8,
            padding: '10px 22px', minHeight: 44, borderRadius: 'var(--radius-button)',
            background: telHref ? 'var(--color-accent)' : 'var(--color-ink-200)',
            color: 'var(--color-cream)', textDecoration: 'none',
            fontSize: 15, fontWeight: 600,
            pointerEvents: telHref ? undefined : 'none',
          }}
        >
          <Phone size={16} strokeWidth={2} /> Call
        </a>
        <span style={{ fontSize: 12, color: 'var(--color-ink-400)' }}>
          Calls use your phone app — log the outcome below when you&apos;re done.
        </span>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
      {!inCall ? (
        <Button variant="primary" size="lg" icon={<Phone size={16} strokeWidth={2} />} onClick={onCall}>
          Call
        </Button>
      ) : (
        <>
          <Button variant="danger" size="lg" icon={<PhoneOff size={16} strokeWidth={2} />} onClick={onHangup}>
            Hang up
          </Button>
          <Button
            variant="secondary"
            size="lg"
            icon={muted ? <MicOff size={16} strokeWidth={2} /> : <Mic size={16} strokeWidth={2} />}
            onClick={onToggleMute}
            disabled={state !== 'in-call'}
          >
            {muted ? 'Unmute' : 'Mute'}
          </Button>
        </>
      )}
      {state !== 'idle' && (
        <span style={{ fontSize: 13, fontWeight: 600, color: state === 'in-call' ? 'var(--color-moss)' : 'var(--color-ink-600)' }}>
          {STATE_LABEL[state]}
          {state === 'in-call' && (
            <span className="tabular" style={{ marginLeft: 8, color: 'var(--color-ink-600)' }}>
              {fmtElapsed(elapsedSec)}
            </span>
          )}
        </span>
      )}
    </div>
  )
}
