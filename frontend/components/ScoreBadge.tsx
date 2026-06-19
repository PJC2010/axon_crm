import type { ScoreGrade } from '@/lib/types'

/* Pill colors mapped to semantic tokens so they adapt to the active theme */
const GRADE_COLORS: Record<string, { bg: string; text: string; dot: string }> = {
  A: { bg: 'var(--color-success-bg)', text: 'var(--color-success)', dot: 'var(--color-success)' }, /* success / moss */
  B: { bg: 'var(--color-info-bg)',    text: 'var(--color-info)',    dot: 'var(--color-info)' },    /* info / ocean */
  C: { bg: 'var(--color-gold-bg)',    text: 'var(--color-gold)',    dot: 'var(--color-gold)' },    /* warning / gold */
  D: { bg: 'var(--color-danger-bg)',  text: 'var(--color-danger)',  dot: 'var(--color-danger)' },  /* danger / rose */
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
