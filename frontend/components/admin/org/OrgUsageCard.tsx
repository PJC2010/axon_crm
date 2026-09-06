'use client'
import { useEffect, useState } from 'react'
import { adminAccountUsage } from '@/lib/api'
import type { AdminAccountUsage } from '@/lib/types'
import { SkeletonCards } from '@/components/ds'
import { DegradedBanner, dash } from '../Degraded'

const CARD: React.CSSProperties = {
  background: 'var(--color-surface)', borderRadius: 'var(--radius-card)',
  boxShadow: 'var(--shadow-card)', padding: 16, marginBottom: 18,
}

/** What this org costs the platform over a window — the per-org view of the
 *  Usage tab. Every figure can be "—" when its query was cut off. */
export function OrgUsageCard({ accountId }: { accountId: number }) {
  const [days, setDays] = useState(30)
  const [data, setData] = useState<AdminAccountUsage | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    adminAccountUsage(accountId, days)
      .then((d) => { if (alive) { setData(d); setError(null) } })
      .catch((e: unknown) => { if (alive) setError(e instanceof Error ? e.message : 'Failed to load usage') })
    return () => { alive = false }
  }, [accountId, days])

  // The response carries its own window, so a stale answer for the previous
  // range renders as loading rather than as the wrong numbers — and nothing
  // has to be reset inside the effect.
  const current = data && data.days === days ? data : null
  const m = current?.metrics
  const tiles: { label: string; value: string; sub?: string }[] = m ? [
    { label: 'RentCast requests', value: dash(m.rentcast_requests) },
    { label: 'Scored reveals · month', value: dash(m.scoring_reveals), sub: `limit ${m.scoring_limit === null ? '∞' : m.scoring_limit.toLocaleString()}` },
    { label: 'Pipeline runs', value: dash(m.runs), sub: `${dash(m.skip_traces)} skip traces` },
    { label: 'SMS sent', value: dash(m.sms_sent) },
    { label: 'Email sent', value: dash(m.email_sent) },
    { label: 'Calls', value: dash(m.calls), sub: `${dash(m.call_minutes)} min` },
    { label: 'Twilio numbers', value: dash(m.tracking_numbers_active), sub: 'active now' },
    { label: 'Territories run', value: dash(m.territories) },
  ] : []

  return (
    <div style={CARD}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <h2 className="t-eyebrow" style={{ margin: 0 }}>Usage · {days} days</h2>
        <select className="select-field" value={days} onChange={(e) => setDays(Number(e.target.value))} style={{ fontSize: 12.5 }}>
          {[7, 30, 90].map((d) => <option key={d} value={d}>{d} days</option>)}
        </select>
      </div>
      {current && <DegradedBanner sources={[{ source: 'Usage', items: current.degraded }]} />}
      {error && <p style={{ margin: 0, color: 'var(--color-danger)', fontSize: 13 }}>{error}</p>}
      {!current && !error && <SkeletonCards count={4} columns={4} h={64} gap={10} />}
      {m && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 10 }}>
          {tiles.map((t) => (
            <div key={t.label} style={{ background: 'var(--color-paper)', borderRadius: 'var(--radius-card)', padding: '10px 12px' }}>
              <span className="t-eyebrow" style={{ display: 'block', marginBottom: 4 }}>{t.label}</span>
              <span className="tabular" style={{ fontSize: 18, fontWeight: 700, color: 'var(--color-ink-900)' }}>{t.value}</span>
              {t.sub && <span style={{ display: 'block', fontSize: 11.5, color: 'var(--color-ink-400)', marginTop: 2 }}>{t.sub}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
