'use client'
import { useEffect, useState } from 'react'
import { Activity, MailCheck, MapPin, Webhook, Zap } from 'lucide-react'
import { adminBacklog } from '@/lib/api'
import type { AdminBacklog } from '@/lib/types'
import { KpiTile } from '@/components/home/dashboardKit'
import { SkeletonCards } from '@/components/ds'
import { fmtDateTime } from '../AdminTable'
import { DegradedBanner, dash } from '../Degraded'
import { apiErr } from '../UserModals'

/* Queues and stale work. Each tile is one soft_query block on the server, so
   any of them can be "—" while the rest answer — never a 0 that means
   "unknown". */

export function OpsBacklog({ refreshKey }: { refreshKey: number }) {
  const [data, setData] = useState<AdminBacklog | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    adminBacklog()
      .then((d) => { if (alive) { setData(d); setError(null) } })
      .catch((e: unknown) => { if (alive) setError(apiErr(e, 'Failed to load the backlog')) })
    return () => { alive = false }
  }, [refreshKey])

  if (error) return <p style={{ color: 'var(--color-danger)', fontSize: 13 }}>{error}</p>
  if (!data) return <div style={{ marginBottom: 22 }}><SkeletonCards count={5} columns={5} h={116} gap={12} /></div>

  const icon = (I: typeof Activity) => <I size={14} strokeWidth={1.5} color="var(--color-ink-400)" />
  const runs = data.runs
  const gq = data.geocode_queue
  const tokens = data.verify_tokens
  const hooks = data.stripe_webhooks
  const firings = data.workflow_firings
  const staleRuns = runs ? runs.queued_stale + runs.running_stale : null
  const staleHours = Math.round((data.stale_after_seconds / 3600) * 10) / 10

  return (
    <div style={{ marginBottom: 22 }}>
      <DegradedBanner sources={[{ source: 'Backlog', items: data.degraded }]} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
        <KpiTile icon={icon(Activity)} label="Pipeline runs active" value={runs ? dash(runs.queued + runs.running) : '—'}
          context={runs ? `${dash(runs.queued)} queued · ${dash(runs.running)} running${staleRuns ? ` · ${staleRuns} stale` : ''}` : undefined}
          contextTone={staleRuns ? 'danger' : 'muted'} />
        <KpiTile icon={icon(MapPin)} label="Geocode queue" value={dash(gq?.queued)}
          context={gq ? `${dash(gq.failed)} failed${gq.oldest_queued_at ? ` · oldest ${fmtDateTime(gq.oldest_queued_at)}` : ''}` : undefined}
          contextTone={(gq?.failed ?? 0) > 0 ? 'danger' : 'muted'} />
        <KpiTile icon={icon(Webhook)} label="Stripe webhooks unprocessed" value={dash(hooks?.received)}
          context={hooks ? `${dash(hooks.error_7d)} errors in 7 d · last ${fmtDateTime(hooks.last_received_at)}` : undefined}
          contextTone={(hooks?.received ?? 0) > 0 || (hooks?.error_7d ?? 0) > 0 ? 'danger' : 'muted'} />
        <KpiTile icon={icon(MailCheck)} label="Verify-email tokens live" value={dash(tokens?.live)}
          context={tokens ? `${dash(tokens.expired_unused)} expired unused` : undefined} />
        <KpiTile icon={icon(Zap)} label="Workflow firings · 24 h" value={dash(firings?.fired_24h)}
          context={firings ? `across ${dash(firings.accounts_24h)} orgs` : undefined} />
      </div>
      <p style={{ margin: '8px 2px 0', fontSize: 12, color: 'var(--color-ink-400)' }}>
        A queued run is stale after 1 h and a running one after {staleHours} h (RUN_MAX_SECONDS); the hourly reconcile marks those failed.
      </p>
    </div>
  )
}
