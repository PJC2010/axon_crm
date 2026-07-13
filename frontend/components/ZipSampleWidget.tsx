'use client'
import { useEffect, useRef, useState, FormEvent } from 'react'
import { ArrowRight, Loader2, MapPin } from 'lucide-react'
import { getZipSample, type ZipSampleResult } from '@/lib/api'

const TRADES = [
  { value: '', label: 'Any trade' },
  { value: 'roofing', label: 'Roofing' },
  { value: 'hvac', label: 'HVAC' },
  { value: 'pool_maintenance', label: 'Pool & spa' },
  { value: 'solar', label: 'Solar' },
  { value: 'epoxy_flooring', label: 'Epoxy flooring' },
  { value: 'fencing', label: 'Fencing' },
  { value: 'landscaping', label: 'Landscaping' },
  { value: 'pressure_washing', label: 'Pressure washing' },
]

const GRADE_STYLE: Record<string, { bg: string; fg: string }> = {
  A: { bg: 'var(--color-success-bg)', fg: 'var(--color-success)' },
  B: { bg: 'var(--color-info-bg)', fg: 'var(--color-info)' },
}

// Poll cadence while a first-time ZIP is being scored server-side.
const POLL_MS = 10_000
const MAX_POLLS = 18 // ~3 minutes, then we stop hammering

/** The landing page's "see your ZIP's top leads — free" teaser (audit P1's
 *  highest-leverage build). Talks to the public, unauthenticated sample
 *  endpoint; everything it renders is masked server-side. */
export function ZipSampleWidget() {
  const [zip, setZip] = useState('')
  const [trade, setTrade] = useState('roofing')
  const [state, setState] = useState<'idle' | 'loading' | 'queued' | 'done' | 'unsupported' | 'error'>('idle')
  const [result, setResult] = useState<ZipSampleResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const polls = useRef(0)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])

  async function fetchSample(zipCode: string, tradeKey: string, isPoll = false) {
    if (!isPoll) {
      setState('loading')
      setError(null)
      polls.current = 0
    }
    try {
      const res = await getZipSample(zipCode, tradeKey || undefined)
      if (!res.configured) {
        setState('unsupported')
        setResult(null)
        return
      }
      if (res.available) {
        setResult(res)
        setState('done')
        return
      }
      if (res.queued && polls.current < MAX_POLLS) {
        polls.current += 1
        setState('queued')
        timer.current = setTimeout(() => fetchSample(zipCode, tradeKey, true), POLL_MS)
        return
      }
      setState('unsupported')
    } catch (err) {
      const msg = err instanceof Error ? err.message : ''
      setError(msg.includes('429') ? 'Easy there — try again in a few minutes.' : 'Something went wrong — try again.')
      setState('error')
    }
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!/^\d{5}$/.test(zip.trim())) {
      setError('Enter a 5-digit ZIP code.')
      setState('error')
      return
    }
    if (timer.current) clearTimeout(timer.current)
    fetchSample(zip.trim(), trade)
  }

  return (
    <div className="lp-zip-widget">
      <form onSubmit={handleSubmit} className="lp-zip-form">
        <input
          type="text"
          inputMode="numeric"
          maxLength={5}
          placeholder="Your ZIP — try 77007"
          value={zip}
          onChange={(e) => setZip(e.target.value.replace(/\D/g, ''))}
          aria-label="ZIP code"
        />
        <select value={trade} onChange={(e) => setTrade(e.target.value)} aria-label="Your trade">
          {TRADES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
        </select>
        <button type="submit" className="lp-btn lp-btn-accent" disabled={state === 'loading'}>
          {state === 'loading' ? <Loader2 size={15} className="lp-spin" /> : <MapPin size={15} />}
          Show my leads
        </button>
      </form>

      {state === 'error' && error && <p className="lp-zip-note lp-zip-error">{error}</p>}

      {state === 'queued' && (
        <p className="lp-zip-note">
          <Loader2 size={13} className="lp-spin" /> First time anyone&apos;s asked about this ZIP —
          we&apos;re scoring it from county records right now. This takes a couple of minutes;
          the list will appear here.
        </p>
      )}

      {state === 'unsupported' && (
        <p className="lp-zip-note">
          We can&apos;t sample that ZIP yet (free county data covers Harris County, TX today).{' '}
          <a href="/preview">Explore the live demo instead</a> — or{' '}
          <a href="/signup">start free</a> and run any territory.
        </p>
      )}

      {state === 'done' && result?.leads && (
        <div className="lp-zip-results">
          <div className="lp-zip-stats">
            <span><b>{result.total_scored?.toLocaleString()}</b> properties scored in {result.zip}</span>
            <span><b>{result.grade_a}</b> grade A</span>
            <span><b>{result.grade_b}</b> grade B</span>
          </div>
          <ol className="lp-zip-list">
            {result.leads.map((lead, i) => (
              <li key={i}>
                <span
                  className="lp-zip-grade"
                  style={{
                    background: GRADE_STYLE[lead.grade]?.bg ?? 'var(--color-ink-100)',
                    color: GRADE_STYLE[lead.grade]?.fg ?? 'var(--color-ink-600)',
                  }}
                >
                  {lead.grade}
                </span>
                <span className="lp-zip-addr">
                  {lead.address}
                  <em>{lead.why}</em>
                </span>
                <span className="lp-zip-meta">
                  {lead.value && <b>{lead.value}</b>}
                  {lead.year_built ? <span>built {lead.year_built}</span> : null}
                  <span className="lp-zip-score">{lead.score}</span>
                </span>
              </li>
            ))}
          </ol>
          <div className="lp-zip-gate">
            <p>Full addresses, owner names, and phone numbers unlock with a free account.</p>
            <a className="lp-btn lp-btn-accent" href="/signup">
              Start free — see the full list <ArrowRight size={15} />
            </a>
          </div>
        </div>
      )}
    </div>
  )
}
