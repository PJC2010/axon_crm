'use client'
import { useEffect, useState } from 'react'
import {
  Building2, Crosshair, Database, Globe, HelpCircle, Landmark, ListChecks, MapPin, RefreshCw,
} from 'lucide-react'
import { adminDataHealth, adminDataHealthRefresh } from '@/lib/api'
import type { AdminDataHealth } from '@/lib/types'
import { KpiTile } from '@/components/home/dashboardKit'
import { SkeletonCards } from '@/components/ds'
import { ToastStack, useToast } from '@/components/Toast'
import { fmtDate, fmtDateTime } from './AdminTable'
import { DegradedBanner, dash, pctText } from './Degraded'
import { apiErr } from './UserModals'
import { DataAlerts } from './data/DataAlerts'
import { DataZipTable } from './data/DataZipTable'
import { DataAccountsTable } from './data/DataAccountsTable'
import { DataSideTables } from './data/DataSideTables'

/* The shared data layer's vital signs. The heavy figures come from a nightly
   snapshot (api/data_health.py) — never computed on this page load — and the
   header says how old it is; Refresh recomputes in the background. */

function age(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime()
  const h = ms / 3.6e6
  if (h < 1) return `${Math.max(1, Math.round(ms / 6e4))} min ago`
  if (h < 48) return `${Math.round(h)} h ago`
  return `${Math.round(h / 24)} d ago`
}

export function AdminData() {
  const [data, setData] = useState<AdminDataHealth | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  // Bumped to re-read: by the refresh button and by the poll below.
  const [tick, setTick] = useState(0)
  const { toasts, show, dismiss } = useToast()

  useEffect(() => {
    let alive = true
    adminDataHealth()
      .then((d) => { if (alive) { setData(d); setError(null) } })
      .catch((e: unknown) => { if (alive) setError(apiErr(e, 'Failed to load data health')) })
    return () => { alive = false }
  }, [tick])

  // While a refresh is running, poll every 10 s (cap 5 min) so the new
  // snapshot appears without a reload.
  const running = data?.refresh?.running === true
  useEffect(() => {
    if (!running) return
    let ticks = 0
    const id = window.setInterval(() => {
      if (++ticks > 30) { window.clearInterval(id); return }
      setTick((t) => t + 1)
    }, 10_000)
    return () => window.clearInterval(id)
  }, [running])

  async function refresh() {
    setRefreshing(true)
    try {
      await adminDataHealthRefresh()
      show('Snapshot queued — this takes a few minutes')
      // The job inserts its `running` row a moment after we return; re-read
      // shortly so the header (and the poll above) pick it up.
      window.setTimeout(() => setTick((t) => t + 1), 2500)
    } catch (e: unknown) {
      show(apiErr(e, 'Could not queue a refresh'), 'error')
    } finally {
      setRefreshing(false)
    }
  }

  if (error) return <p style={{ color: 'var(--color-danger)', fontSize: 13 }}>{error}</p>
  if (!data) return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <SkeletonCards count={4} columns={4} h={88} gap={12} />
      <SkeletonCards count={2} columns={2} h={180} gap={12} />
    </div>
  )

  const icon = (I: typeof Database) => <I size={14} strokeWidth={1.5} color="var(--color-ink-400)" />
  const snap = data.snapshot
  const report = snap?.report
  const parcels = report?.parcels ?? null
  const hcad = report?.hcad ?? null
  const summary = data.summary
  const gq = data.live.geocode_queue
  const leadsUnclassified = data.accounts.reduce<number | null>((acc, a) => {
    if (acc === null || a.unclassified_live === null) return null
    return acc + a.unclassified_live
  }, 0)
  const matchTone = summary?.match_rate_pct != null && summary.match_rate_pct < 90 ? 'danger' : 'muted'

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
        <h2 className="t-eyebrow" style={{ margin: 0 }}>Data health</h2>
        <span style={{ fontSize: 12.5, color: 'var(--color-ink-500)' }}>
          {snap
            ? <>Snapshot #{snap.id} · {snap.status} · {age(snap.started_at)} · {report?.duration_seconds ?? '—'}s{snap.host ? ` on ${snap.host}` : ''} · {snap.triggered_by}</>
            : 'No snapshot yet — the nightly job has not run.'}
        </span>
        {data.refresh?.running && (
          <span style={{ fontSize: 12.5, color: 'var(--color-gold)' }}>Computing… started {age(data.refresh.started_at)}</span>
        )}
        {data.refresh?.stalled && (
          <span style={{ fontSize: 12.5, color: 'var(--color-danger)' }}>A run started {age(data.refresh.started_at)} never finished — the process may have restarted.</span>
        )}
        {data.refresh?.status === 'error' && (
          <span style={{ fontSize: 12.5, color: 'var(--color-danger)' }}>Last run failed: {data.refresh.error ?? 'unknown error'}</span>
        )}
        <button
          className="btn-secondary"
          style={{ marginLeft: 'auto', fontSize: 12.5, padding: '4px 10px', display: 'inline-flex', alignItems: 'center', gap: 5 }}
          disabled={refreshing || running}
          onClick={refresh}
        >
          <RefreshCw size={12} strokeWidth={1.5} /> {running ? 'Refreshing…' : 'Refresh now'}
        </button>
      </div>

      <DegradedBanner sources={[{ source: 'Live figures', items: data.degraded }, { source: 'Snapshot', items: report?.blocks_failed ?? [] }]} />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(215px, 1fr))', gap: 12, marginBottom: 26 }}>
        <KpiTile icon={icon(Database)} label="Parcels cached" value={dash(parcels?.total)}
          context={parcels ? `${dash(parcels.with_apn)} with APN · updated ${fmtDate(parcels.last_updated_at)}` : 'no snapshot'} />
        <KpiTile icon={icon(MapPin)} label="With coordinates" value={pctText(summary?.coords_pct)}
          context={parcels ? `${dash(parcels.with_coords)} of ${dash(parcels.total)}` : undefined} />
        <KpiTile icon={icon(Crosshair)} label="APN → centroid match" value={pctText(summary?.match_rate_pct)}
          context={report?.apn_match ? `${dash(report.apn_match.matched)} of ${dash(report.apn_match.with_apn)} with an APN` : undefined}
          contextTone={matchTone} />
        <KpiTile icon={icon(HelpCircle)} label="Unclassified parcels" value={dash(parcels?.unclassified)}
          context={summary?.unclassified_pct != null ? `${pctText(summary.unclassified_pct)} of the cache` : undefined}
          contextTone={(parcels?.unclassified ?? 0) > 0 ? 'danger' : 'muted'} />
        <KpiTile icon={icon(Building2)} label="Non-residential" value={pctText(summary?.non_residential_pct)}
          context={parcels ? `${dash(parcels.non_residential)} parcels excluded from seeds` : undefined} />
        <KpiTile icon={icon(Landmark)} label="HCAD mirror" value={dash(hcad?.properties)}
          context={hcad ? `${dash(hcad.permits)} permits · source ${data.live.hcad_source}` : `source ${data.live.hcad_source}`}
          contextTone={data.live.hcad_source === 'none' ? 'danger' : 'muted'} />
        <KpiTile icon={icon(Globe)} label="Parcel centroids" value={dash(hcad?.centroids)}
          context={hcad ? `loaded ${fmtDateTime(hcad.centroids_loaded_at)}` : undefined} />
        <KpiTile icon={icon(ListChecks)} label="Leads unclassified · live" value={dash(leadsUnclassified)}
          context={`${data.rule.accounts_stale} stale · ${data.rule.accounts_unstamped} unstamped orgs`}
          contextTone={data.rule.accounts_stale + data.rule.accounts_unstamped > 0 ? 'danger' : 'muted'} />
        <KpiTile icon={icon(MapPin)} label="Geocode queue" value={dash(gq?.queued)}
          context={gq ? `${dash(gq.failed)} failed` : undefined}
          contextTone={(gq?.failed ?? 0) > 0 ? 'danger' : 'muted'} />
      </div>

      <DataAlerts alerts={data.alerts} />
      <DataZipTable zips={data.zips} />
      <DataAccountsTable accounts={data.accounts} />
      <DataSideTables data={data} />
      <ToastStack toasts={toasts} onDismiss={dismiss} />
    </div>
  )
}
