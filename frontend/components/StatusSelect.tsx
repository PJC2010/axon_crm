'use client'
import { useState } from 'react'
import type { LeadStatus } from '@/lib/types'
import { updateStatus } from '@/lib/api'

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

/* Colors matched to Axon semantic palette */
const STATUS_STYLES: Record<LeadStatus, React.CSSProperties> = {
  new:            { background: 'var(--color-ink-50)',    color: 'var(--color-ink-600)' },
  contacted:      { background: 'var(--color-info-bg)',   color: 'var(--color-info)' },
  qualified:      { background: 'var(--color-accent-50)', color: 'var(--color-accent)' },
  not_interested: { background: 'var(--color-danger-bg)', color: 'var(--color-danger)' },
  converted:      { background: 'var(--color-success-bg)',color: 'var(--color-success)' },
  quote_sent:     { background: 'var(--color-gold-bg)',   color: 'var(--color-gold)' },
  won:            { background: 'var(--color-success-bg)',color: 'var(--color-success)' },
  lost:           { background: 'var(--color-ink-50)',    color: 'var(--color-ink-500)' },
}

const CHEVRON_SVG = "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%236E7585' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")"

interface Props {
  leadId: number
  value: LeadStatus
  onChange?: (s: LeadStatus) => void
}

export function StatusSelect({ leadId, value, onChange }: Props) {
  const [saving, setSaving] = useState(false)

  async function handleChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const next = e.target.value as LeadStatus
    setSaving(true)
    try {
      await updateStatus(leadId, next)
      onChange?.(next)
    } finally {
      setSaving(false)
    }
  }

  return (
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
  )
}
