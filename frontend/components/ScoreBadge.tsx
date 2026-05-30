import type { ScoreGrade } from '@/lib/types'

/* Pill colors matched to Axon semantic palette */
const GRADE_COLORS: Record<string, { bg: string; text: string; dot: string }> = {
  A: { bg: '#E6EEDE', text: '#3D5C39', dot: '#4F7A4A' },   /* success / moss */
  B: { bg: '#DCE7ED', text: '#1F4258', dot: '#2E5F7A' },   /* info / ocean */
  C: { bg: '#F4E7CB', text: '#7A5419', dot: '#B07A2A' },   /* warning / gold */
  D: { bg: '#F0D9D6', text: '#7A2F26', dot: '#A84236' },   /* danger / rose */
}

interface Props {
  grade: ScoreGrade | null
  score?: number | null
}

export function ScoreBadge({ grade, score }: Props) {
  if (!grade) return <span style={{ color: 'var(--color-ink-400)', fontSize: 13 }}>—</span>

  const c = GRADE_COLORS[grade]
  if (!c) return <span style={{ color: 'var(--color-ink-400)', fontSize: 13 }}>—</span>

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        padding: '3px 9px',
        borderRadius: 9999,
        background: c.bg,
        color: c.text,
        fontSize: 12,
        fontWeight: 600,
        lineHeight: 1.5,
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: c.dot,
          flexShrink: 0,
        }}
      />
      <span style={{ fontFamily: 'var(--font-display)' }}>{grade}</span>
      {score != null && (
        <span className="tabular" style={{ opacity: 0.7 }}>{Math.round(score)}</span>
      )}
    </span>
  )
}
