'use client'
import { Plus } from 'lucide-react'
import type { PipelineCardLead } from '@/lib/types'
import { ScoreBadge } from './ScoreBadge'

interface Props {
  lead: PipelineCardLead
  onQuickTask?: (lead: PipelineCardLead) => void
  /** When true, render the lighter "ghost" variant used by the drag layer. */
  ghost?: boolean
}

const fmt = (v: number | null) =>
  v != null ? '$' + v.toLocaleString() : null

export function KanbanCard({ lead, onQuickTask, ghost = false }: Props) {
  return (
    <div
      style={{
        padding: '10px 12px',
        background: 'var(--color-paper)',
        border: '1px solid var(--color-ink-200)',
        borderRadius: 'var(--radius-card)',
        cursor: ghost ? 'grabbing' : 'pointer',
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        boxShadow: ghost ? 'var(--shadow-lg, 0 12px 28px rgba(0,0,0,0.18))' : undefined,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-ink-900)', lineHeight: 1.35, flex: 1 }}>
          {lead.address || lead.contact_name || '—'}
        </span>
        {lead.score_grade && <ScoreBadge grade={lead.score_grade} score={lead.lead_score} />}
      </div>
      {(lead.owner_name || lead.contact_name) && (
        <span style={{ fontSize: 12.5, color: 'var(--color-ink-500)' }}>{lead.owner_name || lead.contact_name}</span>
      )}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        {lead.estimated_job_value != null ? (
          <span className="tabular" style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-accent-300)' }}>
            {fmt(lead.estimated_job_value)}
          </span>
        ) : <span />}
        {onQuickTask && !ghost && (
          <button
            type="button"
            data-no-drag
            onClick={e => { e.stopPropagation(); onQuickTask(lead) }}
            title="Add a task for this lead"
            aria-label="Add a task for this lead"
            style={{
              width: 28, height: 28, borderRadius: '50%',
              background: 'var(--color-ink-100)',
              border: '1px solid var(--color-ink-200)',
              color: 'var(--color-ink-500)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              cursor: 'pointer', flexShrink: 0,
            }}
            onMouseEnter={e => {
              e.currentTarget.style.background = 'var(--color-accent)'
              e.currentTarget.style.color = 'white'
              e.currentTarget.style.borderColor = 'var(--color-accent)'
            }}
            onMouseLeave={e => {
              e.currentTarget.style.background = 'var(--color-ink-100)'
              e.currentTarget.style.color = 'var(--color-ink-500)'
              e.currentTarget.style.borderColor = 'var(--color-ink-200)'
            }}
          >
            <Plus size={14} strokeWidth={2.5} />
          </button>
        )}
      </div>
    </div>
  )
}
