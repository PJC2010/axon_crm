'use client'
import { useEffect, useState } from 'react'
import { ThumbsDown, X } from 'lucide-react'
import { createLeadEvent } from '@/lib/api'

// Reasons a lead is a hard negative (bad data / not a real opportunity). Stored
// in the disqualified event's metadata.reason; the labeling job treats these as
// negatives and the reasons feed future data-quality fixes.
const REASONS: { key: string; label: string }[] = [
  { key: 'wrong_property_type', label: 'Wrong property type' },
  { key: 'bad_data', label: 'Bad or missing data' },
  { key: 'not_a_prospect', label: 'Not a real prospect' },
  { key: 'duplicate', label: 'Duplicate' },
  { key: 'other', label: 'Other' },
]

/**
 * "Bad lead" action. Emits a `disqualified` lead event with the chosen reason —
 * the one outcome event the contractor raises explicitly (everything else is
 * instrumented automatically server-side). One decisive click per reason; no
 * required free-text.
 */
export function DisqualifyButton({ leadId, onDone }: { leadId: number; onDone?: (reason: string) => void }) {
  const [open, setOpen] = useState(false)
  const [submitting, setSubmitting] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function submit(reason: string) {
    setSubmitting(reason)
    setError(null)
    try {
      await createLeadEvent(leadId, { event_type: 'disqualified', metadata: { reason } })
      setOpen(false)
      onDone?.(reason)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to submit')
    } finally {
      setSubmitting(null)
    }
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="dash-icon-btn borderless"
        title="Flag as a bad lead"
        aria-label="Flag as a bad lead"
      >
        <ThumbsDown size={16} strokeWidth={1.5} />
      </button>
      {open && (
        <ReasonPicker
          submitting={submitting}
          error={error}
          onPick={submit}
          onClose={() => { if (!submitting) { setOpen(false); setError(null) } }}
        />
      )}
    </>
  )
}

function ReasonPicker({
  submitting, error, onPick, onClose,
}: {
  submitting: string | null
  error: string | null
  onPick: (reason: string) => void
  onClose: () => void
}) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <>
      <div
        onClick={onClose}
        style={{ position: 'fixed', inset: 0, background: 'rgba(22,24,29,0.4)', backdropFilter: 'blur(2px)', zIndex: 300 }}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="disqualify-title"
        style={{
          position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%, -50%)',
          zIndex: 301, width: 'min(420px, calc(100vw - 32px))',
          background: 'var(--color-surface)', borderRadius: 'var(--radius-modal)',
          boxShadow: 'var(--shadow-modal)', padding: '24px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 16 }}>
          <div style={{ flex: 1 }}>
            <p id="disqualify-title" style={{ margin: 0, fontSize: 15, fontWeight: 600, color: 'var(--color-ink-900)' }}>
              Flag as a bad lead
            </p>
            <p style={{ margin: '6px 0 0', fontSize: 13, color: 'var(--color-ink-500)', lineHeight: 1.5 }}>
              Why isn&apos;t this a real opportunity? This helps improve lead scoring.
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Cancel"
            style={{ flexShrink: 0, background: 'none', border: 'none', cursor: 'pointer', padding: 4, color: 'var(--color-ink-400)', display: 'flex' }}
          >
            <X size={16} />
          </button>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {REASONS.map(r => (
            <button
              key={r.key}
              onClick={() => onPick(r.key)}
              disabled={submitting !== null}
              className="btn-secondary"
              style={{
                justifyContent: 'flex-start', textAlign: 'left', width: '100%',
                opacity: submitting !== null && submitting !== r.key ? 0.5 : 1,
                cursor: submitting !== null ? 'not-allowed' : 'pointer',
              }}
            >
              {submitting === r.key ? 'Saving…' : r.label}
            </button>
          ))}
        </div>

        {error && (
          <p style={{ margin: '12px 0 0', fontSize: 12, color: 'var(--color-danger)' }}>{error}</p>
        )}
      </div>
    </>
  )
}
