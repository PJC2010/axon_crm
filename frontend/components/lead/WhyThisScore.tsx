'use client'
import { useEffect, useState } from 'react'
import type { ScoreExplanation, ScoreFactor } from '@/lib/types'
import { getScoreExplanation } from '@/lib/api'
import { ScoreBadge } from '../ScoreBadge'
import { VERTICAL_LABELS } from './format'

/** Plain-language read of a grade, so a non-technical user knows what to *do*
 *  with this lead the moment they open the card. */
const GRADE_MEANING: Record<string, string> = {
  A: 'Strong lead — one of your best prospects. Reach out first.',
  B: 'Good lead — solid potential. Worth a timely follow-up.',
  C: 'Fair lead — an average fit. Pursue when you have capacity.',
  D: 'Weak lead — low fit on the signals we scored.',
  F: 'Weak lead — low fit on the signals we scored.',
}

/** "Why this score" — a plain-language verdict, the drivers that lifted the
 *  score, and the full per-factor breakdown behind a toggle. Written so a
 *  layperson can read it without knowing how scoring works.
 *
 *  Self-fetching by default (drawer + full lead page pass only a leadId), but an
 *  `explanation` can be injected directly — used by the dev preview so the card
 *  renders without an API/login. */
export function WhyThisScore({
  leadId,
  explanation: injected,
}: {
  leadId: number
  explanation?: ScoreExplanation
}) {
  const [fetched, setFetched] = useState<ScoreExplanation | null>(null)
  const [showAll, setShowAll] = useState(false)

  useEffect(() => {
    if (injected) return
    setFetched(null)
    setShowAll(false)
    getScoreExplanation(leadId).then(setFetched).catch(() => {})
  }, [leadId, injected])

  const explanation = injected ?? fetched
  if (!explanation || explanation.factors.length === 0) return null
  const {
    factors, top_drivers, summary, grade, score, vertical, vertical_description,
    is_default_profile, weights_drift, score_updated_at, region, region_label,
  } = explanation

  const scoredDaysAgo = score_updated_at
    ? Math.floor((Date.now() - new Date(score_updated_at).getTime()) / 86_400_000)
    : null

  const profileName = is_default_profile
    ? 'Default scoring profile'
    : (vertical ? (VERTICAL_LABELS[vertical] ?? vertical) : 'Scoring profile')
  const topWeights = vertical_description
    .slice(0, 3)
    .map(f => `${f.label} ${Math.round(f.weight * 100)}%`)
    .join(' · ')
  // Bar widths stay comparable across the default and expanded lists.
  const maxContribution = Math.max(...factors.map(f => f.contribution), 1)

  // Show the top drivers by default; fall back to the first few factors so the
  // panel is never empty when nothing has a positive contribution.
  const driverFactors = factors.filter(f => top_drivers.includes(f.key))
  const primary = driverFactors.length ? driverFactors : factors.slice(0, 3)
  const rest = factors.filter(f => !primary.includes(f))

  const gradeMeaning = grade ? GRADE_MEANING[grade] : null

  const renderFactor = (f: ScoreFactor) => {
    const isTop = top_drivers.includes(f.key)
    const pct = Math.round((f.contribution / maxContribution) * 100)
    return (
      <div key={f.key}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, marginBottom: 3 }}>
          <span style={{ fontSize: 13, fontWeight: isTop ? 600 : 500, color: isTop ? 'var(--color-ink-900)' : 'var(--color-ink-700)' }}>
            {f.label}
            {isTop && (
              <span style={{
                marginLeft: 6, fontSize: 9, fontWeight: 700, padding: '1px 6px',
                borderRadius: 'var(--radius-pill)', background: 'var(--color-accent-100)',
                color: 'var(--color-accent-300)', textTransform: 'uppercase', letterSpacing: '0.05em',
                whiteSpace: 'nowrap',
              }}>Top reason</span>
            )}
          </span>
          <span className="tabular" style={{ fontSize: 12, fontWeight: 600, color: isTop ? 'var(--color-accent-300)' : 'var(--color-ink-500)', flexShrink: 0 }}>
            +{f.contribution.toFixed(1)} pts
          </span>
        </div>
        {/* Plain description visible inline — was tooltip-only, invisible on touch. */}
        {f.description && (
          <p style={{ margin: '0 0 6px', fontSize: 12, color: 'var(--color-ink-500)', lineHeight: 1.4 }}>
            {f.description}
          </p>
        )}
        <div
          style={{ height: 8, borderRadius: 'var(--radius-pill)', background: 'var(--color-ink-100)', overflow: 'hidden' }}
          role="img"
          aria-label={`${f.label} contributes ${f.contribution.toFixed(1)} points`}
        >
          <div style={{
            height: '100%',
            width: `${pct}%`,
            background: isTop ? 'var(--color-accent)' : 'var(--color-ink-300)',
            borderRadius: 'var(--radius-pill)',
          }} />
        </div>
      </div>
    )
  }

  return (
    <section style={{ padding: '18px 24px', borderBottom: '1px solid var(--color-ink-100)' }}>
      <p className="t-eyebrow" style={{ marginBottom: 10 }}>Why this score</p>

      {/* Verdict line: grade badge + a plain "what this means / what to do" read. */}
      {(grade || gradeMeaning) && (
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, marginBottom: 12 }}>
          <ScoreBadge grade={grade} score={score} style={{ flexShrink: 0, fontSize: 13, padding: '4px 11px' }} />
          {gradeMeaning && (
            <p style={{ margin: 0, fontSize: 14, fontWeight: 600, color: 'var(--color-ink-900)', lineHeight: 1.4 }}>
              {gradeMeaning}
            </p>
          )}
        </div>
      )}

      {/* One-line plain-language reason for this specific lead. */}
      {summary && (
        <p style={{ fontSize: 13, color: 'var(--color-ink-700)', lineHeight: 1.5, margin: '0 0 6px' }}>
          {summary}
        </p>
      )}
      <p style={{ fontSize: 12, color: 'var(--color-ink-500)', lineHeight: 1.5, margin: '0 0 16px' }}>
        Scored on the <span style={{ fontWeight: 600, color: 'var(--color-ink-700)' }}>{profileName}</span>
        {/* Say which market tuned the weights. A lead in a calibrated market is
            scored on different thresholds from the national default, and that
            should read as a stated choice rather than an unexplained number. */}
        {region && region !== 'us' && (
          <>, calibrated for <span style={{ fontWeight: 600, color: 'var(--color-ink-700)' }}>{region_label}</span></>
        )}
        {topWeights && <>, which weighs {topWeights}.</>}
      </p>

      <p className="t-eyebrow" style={{ margin: '0 0 10px', color: 'var(--color-ink-400)' }}>
        What lifted this score
      </p>
      {/* Top drivers by default; full breakdown behind the toggle below */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {primary.map(renderFactor)}
        {showAll && rest.map(renderFactor)}
      </div>

      {rest.length > 0 && (
        <button
          type="button"
          onClick={() => setShowAll(v => !v)}
          style={{
            marginTop: 14, minHeight: 40, padding: '0 4px', background: 'none', border: 'none', cursor: 'pointer',
            fontSize: 13, fontWeight: 600, color: 'var(--color-accent-300)',
            display: 'inline-flex', alignItems: 'center',
          }}
        >
          {showAll ? 'Hide other factors ▴' : `Show all factors (${rest.length} more) ▾`}
        </button>
      )}

      {weights_drift && (
        <p style={{ marginTop: 12, marginBottom: 0, fontSize: 12, color: 'var(--color-warning)' }}>
          Scoring weights changed since this lead was last scored — re-score for an exact match.
        </p>
      )}

      {scoredDaysAgo !== null && scoredDaysAgo > 90 && (
        <p style={{ marginTop: 12, marginBottom: 0, fontSize: 12, color: 'var(--color-warning)' }}>
          Scored {Math.round(scoredDaysAgo / 30)} months ago —
          signals like sale recency fade over time; re-score this ZIP for fresh grades.
        </p>
      )}
    </section>
  )
}
