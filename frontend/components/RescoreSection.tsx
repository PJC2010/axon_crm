'use client'
import { useState } from 'react'
import { RefreshCw, Sparkles } from 'lucide-react'
import { rescoreObjects } from '@/lib/api'
import { useTerminology } from '@/hooks/useTerminology'

// Business types scored from child-object roll-ups (mirrors
// SCORING_PROFILE_BY_BUSINESS_TYPE in pipeline/profiles.py).
const SCORED_TYPES: Record<string, string> = {
  insurance_agency: 'Clients are graded by renewal urgency and cross-sell headroom.',
  retail: 'Customers are graded by recency, frequency, and lifetime spend (RFM).',
}

/**
 * Manual "rescore now" for non-property accounts. Scores also refresh nightly;
 * this is for after a bulk import. Renders nothing for business types that
 * aren't scored this way (home services scores through the pipeline instead).
 */
export function RescoreSection() {
  const { businessType, t } = useTerminology()
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<string | null>(null)

  const blurb = SCORED_TYPES[businessType]
  if (!blurb) return null

  async function handleRescore() {
    setBusy(true)
    setResult(null)
    try {
      const { updated } = await rescoreObjects()
      setResult(`Updated scores on ${updated} ${t('records').toLowerCase()}.`)
    } catch (err: unknown) {
      setResult(err instanceof Error ? err.message : 'Score update failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <Sparkles size={14} strokeWidth={1.5} style={{ color: 'var(--color-accent)' }} />
        <h2 className="t-eyebrow" style={{ margin: 0 }}>Lead scoring</h2>
      </div>
      <p style={{ margin: '0 0 12px', fontSize: 13, color: 'var(--color-ink-500)' }}>
        {blurb} Scores refresh automatically each night — update them now after a bulk import.
      </p>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <button
          onClick={handleRescore}
          disabled={busy}
          className="btn-primary"
          style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 36, padding: '0 14px', fontSize: 13 }}
        >
          <RefreshCw size={13} strokeWidth={1.5} className={busy ? 'animate-spin' : ''} />
          {busy ? 'Updating…' : 'Update scores now'}
        </button>
        {result && <span style={{ fontSize: 13, color: 'var(--color-ink-500)' }}>{result}</span>}
      </div>
    </section>
  )
}
