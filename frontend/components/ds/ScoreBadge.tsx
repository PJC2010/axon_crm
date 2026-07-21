import React from 'react'

const GRADE_COLORS: Record<string, { bg: string; fg: string }> = {
  A: { bg: 'var(--color-success-bg)', fg: 'var(--color-success)' },
  B: { bg: 'var(--color-info-bg)',    fg: 'var(--color-info)' },
  C: { bg: 'var(--color-gold-soft)',  fg: 'var(--color-gold)' },
  D: { bg: 'var(--color-danger-bg)',  fg: 'var(--color-danger)' },
  F: { bg: 'var(--color-danger-bg)',  fg: 'var(--color-danger)' },
}

// Grades framed as actions, not letters (matches WhyThisScore's plain-language
// verdicts): the tooltip/screen-reader text tells the user what to *do*.
const GRADE_ACTION: Record<string, string> = {
  A: 'A — call first',
  B: 'B — worth a timely follow-up',
  C: 'C — when you have capacity',
  D: 'D — low priority',
  F: 'F — low priority',
}

export interface ScoreBadgeProps {
  grade?: string | null
  score?: number | null
  style?: React.CSSProperties
}

/**
 * Lead score pill — an A–F grade with optional numeric score. Color-keyed to
 * the grade; the grade letter is set in the display (slab) face.
 */
export function ScoreBadge({ grade, score, style }: ScoreBadgeProps) {
  if (!grade) return <span style={{ color: 'var(--color-ink-400)', fontSize: 13 }}>—</span>
  const c = GRADE_COLORS[grade] || GRADE_COLORS.F
  const action = GRADE_ACTION[grade]
  return (
    <span
      title={action}
      aria-label={action ? `Lead grade ${action}` : `Lead grade ${grade}`}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 5,
        padding: '3px 9px', borderRadius: 'var(--radius-pill)',
        background: c.bg, color: c.fg,
        fontSize: 12, fontWeight: 600, lineHeight: 1.5, ...style,
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: c.fg, flexShrink: 0 }} />
      <span style={{ fontFamily: 'var(--font-display)' }}>{grade}</span>
      {score != null && (
        <span className="tabular" style={{ opacity: 0.7 }}>{Math.round(score)}</span>
      )}
    </span>
  )
}
