'use client'
import { useState } from 'react'
import { ToastStack, useToast } from './Toast'
import type { LeadStatus } from '@/lib/types'
import { updateStatus } from '@/lib/api'
import { statusTokens } from '@/lib/gradeColors'
import { WonCelebration } from './WonCelebration'

const STATUS_LABELS: Record<LeadStatus, string> = {
  new:            'New',
  contacted:      'Contacted',
  qualified:      'Qualified',
  not_interested: 'Not interested',
  converted:      'Converted',
  quote_sent:     'Quote Sent',
  won:            'Won',
  lost:           'Lost',
}

/* Colors come from the one shared source (lib/gradeColors). This file used to
   define its own map in which `lost` and `not_interested` were swapped relative
   to StatusPill — the same lead read as danger in one place and neutral in the
   other. */
const STATUS_STYLES: Record<LeadStatus, React.CSSProperties> = Object.fromEntries(
  (Object.keys(STATUS_LABELS) as LeadStatus[]).map(k => {
    const t = statusTokens(k)
    return [k, { background: t.bg, color: t.fg }]
  }),
) as Record<LeadStatus, React.CSSProperties>

const CHEVRON_SVG = "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%236E7585' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")"

interface Props {
  leadId: number
  value: LeadStatus
  onChange?: (s: LeadStatus) => void
  /** Job value + label for the won-deal celebration; pass when available. */
  jobValue?: number | null
  celebrateLabel?: string | null
  /** When false, skip the API write and only report through onChange — used by
   *  the no-login /preview demo, where state lives in the page. */
  persist?: boolean
}

export function StatusSelect({ leadId, value, onChange, jobValue, celebrateLabel, persist = true }: Props) {
  const { toasts, show, dismiss } = useToast()
  const [saving, setSaving] = useState(false)
  const [celebrating, setCelebrating] = useState(false)

  async function handleChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const next = e.target.value as LeadStatus
    setSaving(true)
    try {
      if (persist) await updateStatus(leadId, next)
      if (next === 'won') setCelebrating(true)
      onChange?.(next)
    } catch (err) {
      // A masked, past-allowance scored lead can't be worked without a reveal:
      // the API answers 403 (api/scoring_quota.py). Surface it instead of
      // leaving an unhandled rejection, and don't move the control — the select
      // is uncontrolled-adjacent (value prop unchanged), so it snaps back.
      const msg = err instanceof Error ? err.message : String(err)
      show(msg.includes('403')
        ? 'This scored lead is past your monthly reveal allowance. Upgrade your plan to work more scored leads.'
        : "We couldn't update the status. Please try again.", 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
    <ToastStack toasts={toasts} onDismiss={dismiss} />
    {celebrating && (
      <WonCelebration
        deal={{ value: jobValue ?? null, label: celebrateLabel ?? null }}
        onDone={() => setCelebrating(false)}
        // Demo mode (persist=false) has no signed-in app to invoice from.
        invoiceHref={persist ? undefined : null}
      />
    )}
    <select
      value={value}
      onChange={handleChange}
      disabled={saving}
      style={{
        fontFamily: 'var(--font-sans)',
        fontSize: 12,
        padding: '4px 22px 4px 8px',
        borderRadius: 9999,
        border: 'none',
        cursor: saving ? 'not-allowed' : 'pointer',
        opacity: saving ? 0.5 : 1,
        appearance: 'none',
        backgroundImage: CHEVRON_SVG,
        backgroundRepeat: 'no-repeat',
        backgroundPosition: 'right 5px center',
        fontWeight: 600,
        ...STATUS_STYLES[value],
      }}
    >
      {(Object.entries(STATUS_LABELS) as [LeadStatus, string][]).map(([k, label]) => (
        <option key={k} value={k}>{label}</option>
      ))}
    </select>
    </>
  )
}
