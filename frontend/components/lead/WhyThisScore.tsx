'use client'
import { useEffect, useState } from 'react'
import type { ScoreExplanation } from '@/lib/types'
import { getScoreExplanation } from '@/lib/api'
import { VERTICAL_LABELS } from './format'

/** "Why this score" — per-factor breakdown + vertical weighting. Self-fetching
 *  so the drawer and the full lead page can drop it in with just a lead id. */
export function WhyThisScore({ leadId }: { leadId: number }) {
  const [explanation, setExplanation] = useState<ScoreExplanation | null>(null)

  useEffect(() => {
    setExplanation(null)
    getScoreExplanation(leadId).then(setExplanation).catch(() => {})
  }, [leadId])

  if (!explanation || explanation.factors.length === 0) return null
  const { factors, top_drivers, vertical, vertical_description, is_default_profile, weights_drift } = explanation

  const profileName = is_default_profile
    ? 'Default scoring profile'
    : (vertical ? (VERTICAL_LABELS[vertical] ?? vertical) : 'Scoring profile')
  const topWeights = vertical_description
    .slice(0, 3)
    .map(f => `${f.label} ${Math.round(f.weight * 100)}%`)
    .join(' · ')
  const maxContribution = Math.max(...factors.map(f => f.contribution), 1)

  return (
    <section style={{ padding: '16px 24px', borderBottom: '1px solid var(--color-ink-100)' }}>
      <p className="t-eyebrow" style={{ marginBottom: 8 }}>Why this score</p>

      {/* Auto-generated description of what this vertical weighs */}
      <p style={{ fontSize: 12, color: 'var(--color-ink-500)', lineHeight: 1.5, margin: '0 0 14px' }}>
        <span style={{ fontWeight: 600, color: 'var(--color-ink-700)' }}>{profileName}</span>
        {topWeights && <> weighs {topWeights}.</>}
      </p>

      {/* Per-factor breakdown — bar width ∝ point contribution */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {factors.map(f => {
          const isTop = top_drivers.includes(f.key)
          return (
            <div key={f.key} title={f.description}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 3 }}>
                <span style={{ fontSize: 12, fontWeight: isTop ? 600 : 500, color: isTop ? 'var(--color-ink-900)' : 'var(--color-ink-600)' }}>
                  {f.label}
                  {isTop && (
                    <span style={{
                      marginLeft: 6, fontSize: 9, fontWeight: 600, padding: '1px 6px',
                      borderRadius: 'var(--radius-pill)', background: 'var(--color-accent-100)',
                      color: 'var(--color-accent-800)', textTransform: 'uppercase', letterSpacing: '0.05em',
                    }}>Top driver</span>
                  )}
                </span>
                <span className="tabular" style={{ fontSize: 11, color: 'var(--color-ink-400)', flexShrink: 0, marginLeft: 8 }}>
                  +{f.contribution.toFixed(1)} pts · {Math.round(f.weight * 100)}%
                </span>
              </div>
              <div style={{ height: 6, borderRadius: 'var(--radius-pill)', background: 'var(--color-ink-100)', overflow: 'hidden' }}>
                <div style={{
                  height: '100%',
                  width: `${(f.contribution / maxContribution) * 100}%`,
                  background: isTop ? 'var(--color-accent)' : 'var(--color-ink-300)',
                  borderRadius: 'var(--radius-pill)',
                }} />
              </div>
            </div>
          )
        })}
      </div>

      {weights_drift && (
        <p style={{ marginTop: 12, marginBottom: 0, fontSize: 11, color: 'var(--color-warning, #B07A2A)' }}>
          Scoring weights changed since this lead was last scored — re-score for an exact match.
        </p>
      )}
    </section>
  )
}
