'use client'
import { Clock } from 'lucide-react'
import type { LeadStatus, ScoreGrade } from '@/lib/types'
import { coolingDays, COOLING_URGENT_DAYS } from '@/lib/cooling'

/**
 * "5 days untouched" indicator for high-grade leads going cold in early stages.
 * Renders nothing unless the lead is actually cooling (see lib/cooling.ts).
 */
export function CoolingChip({ grade, status, stageMovedAt, createdAt, style }: {
  grade: ScoreGrade | string | null | undefined
  status: LeadStatus | string
  stageMovedAt: string | null | undefined
  createdAt?: string | null
  style?: React.CSSProperties
}) {
  const days = coolingDays(grade, status, stageMovedAt, createdAt)
  if (days == null) return null
  const urgent = days >= COOLING_URGENT_DAYS
  return (
    <span
      title={`Grade ${grade} lead — ${days} days without a stage move. Exclusive leads cool fast.`}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 4,
        padding: '2px 8px', borderRadius: 'var(--radius-pill)',
        background: urgent ? 'var(--color-danger-bg)' : 'var(--color-gold-bg, var(--color-gold-soft))',
        color: urgent ? 'var(--color-danger)' : 'var(--color-gold)',
        fontSize: 10.5, fontWeight: 600, whiteSpace: 'nowrap',
        ...style,
      }}
    >
      <Clock size={10} strokeWidth={2} style={{ flexShrink: 0 }} />
      {days}d untouched
    </span>
  )
}
