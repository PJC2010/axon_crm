'use client'
import { Home, User } from 'lucide-react'
import type { Category, Lead, LeadStatus } from '@/lib/types'
import { ScoreBadge } from '../ScoreBadge'
import { StatusSelect } from '../StatusSelect'
import { CoolingChip } from '../CoolingChip'
import { VERTICAL_LABELS } from './format'

interface Props {
  lead: Lead
  propertyBased: boolean
  categories: Category[]
  selected: boolean
  onToggleSelect: (id: number) => void
  onClick: (lead: Lead) => void
  onStatusChange: (id: number, s: LeadStatus) => void
}

function fmtCompactCurrency(n: number | null | undefined): string | null {
  if (n == null) return null
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`
  return `$${n}`
}

/**
 * Mobile-first lead card — the phone-width rendering of a lead row. The desktop
 * table crams score/status/category/value into columns that force a horizontal
 * scroll on a phone; this stacks the same facts into a tappable card with the
 * primary label and score up top, so a rep can scan the list one-thumb.
 */
export function LeadCard({ lead, propertyBased, categories, selected, onToggleSelect, onClick, onStatusChange }: Props) {
  const Icon = propertyBased ? Home : User
  const primary = propertyBased
    ? (lead.address || lead.contact_name || '—')
    : (lead.contact_name || lead.owner_name || lead.address || '—')
  const secondary = propertyBased
    ? [lead.city, lead.state, lead.zip].filter(Boolean).join(', ')
    : ([lead.city, lead.state].filter(Boolean).join(', ') || lead.account_number || '')

  const catMatch = lead.vertical
    ? (categories.find(c => c.value === lead.vertical)?.label ?? VERTICAL_LABELS[lead.vertical] ?? lead.vertical)
    : null
  const jobValue = fmtCompactCurrency(lead.estimated_job_value)

  return (
    <div
      onClick={() => onClick(lead)}
      style={{
        display: 'flex', gap: 12, padding: '14px', minHeight: 72,
        background: selected ? 'var(--color-surface-hi)' : 'var(--color-surface)',
        border: '1px solid var(--color-ink-200)',
        borderRadius: 'var(--radius-card)',
        cursor: 'pointer',
      }}
    >
      <label
        onClick={e => e.stopPropagation()}
        style={{ display: 'flex', alignItems: 'flex-start', paddingTop: 2, flexShrink: 0 }}
      >
        <input
          type="checkbox"
          checked={selected}
          onChange={() => onToggleSelect(lead.id)}
          aria-label={`Select ${primary}`}
          style={{ width: 18, height: 18, cursor: 'pointer' }}
        />
      </label>

      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Title row: name/address + score badge */}
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, minWidth: 0 }}>
            <Icon size={15} strokeWidth={1.5} style={{ color: 'var(--color-ink-400)', flexShrink: 0 }} />
            <p style={{
              margin: 0, fontSize: 15, fontWeight: 600, color: 'var(--color-ink-900)',
              lineHeight: 1.3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              {primary}
            </p>
          </div>
          <ScoreBadge grade={lead.score_grade} score={lead.lead_score} style={{ flexShrink: 0 }} />
        </div>

        {secondary && (
          <p style={{ margin: '3px 0 0 22px', fontSize: 13, color: 'var(--color-ink-500)' }}>{secondary}</p>
        )}

        {/* Meta row: status + category + value */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
          <span onClick={e => e.stopPropagation()}>
            <StatusSelect
              leadId={lead.id}
              value={lead.status}
              jobValue={lead.estimated_job_value}
              celebrateLabel={primary}
              onChange={s => onStatusChange(lead.id, s)}
            />
          </span>
          {catMatch && (
            <span style={{
              fontSize: 10, fontWeight: 600, padding: '2px 8px', borderRadius: 'var(--radius-pill)',
              background: 'var(--color-accent-100)', color: 'var(--color-accent-300)',
              textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap',
            }}>
              {catMatch}
            </span>
          )}
          <CoolingChip
            grade={lead.score_grade}
            status={lead.status}
            stageMovedAt={lead.stage_moved_at}
            createdAt={lead.created_at}
          />
          {jobValue && (
            <span className="tabular" style={{ marginLeft: 'auto', fontSize: 14, fontWeight: 700, color: 'var(--color-accent-300)' }}>
              {jobValue}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
