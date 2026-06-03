import type { PipelineCardLead } from '@/lib/types'
import { ScoreBadge } from './ScoreBadge'

interface Props {
  lead: PipelineCardLead
  onClick: () => void
}

const fmt = (v: number | null) =>
  v != null ? '$' + v.toLocaleString() : null

export function KanbanCard({ lead, onClick }: Props) {
  return (
    <div
      onClick={onClick}
      style={{
        padding: '10px 12px',
        background: 'var(--color-paper)',
        border: '1px solid var(--color-ink-200)',
        borderRadius: 'var(--radius-card)',
        cursor: 'pointer',
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--color-ink-900)', lineHeight: 1.3, flex: 1 }}>
          {lead.address}
        </span>
        {lead.score_grade && <ScoreBadge grade={lead.score_grade} score={lead.lead_score} />}
      </div>
      {(lead.contact_name || lead.owner_name) && (
        <span style={{ fontSize: 11, color: 'var(--color-ink-400)' }}>{lead.contact_name || lead.owner_name}</span>
      )}
      {lead.estimated_job_value != null && (
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-accent)' }}>
          {fmt(lead.estimated_job_value)}
        </span>
      )}
    </div>
  )
}
