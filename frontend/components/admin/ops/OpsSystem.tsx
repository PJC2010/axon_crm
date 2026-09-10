'use client'
import { Fragment, useEffect, useState } from 'react'
import { adminSystem } from '@/lib/api'
import type { AdminSystemInfo } from '@/lib/types'
import { SkeletonCards } from '@/components/ds'
import { CARD, fmtDateTime } from '../AdminTable'
import { DegradedBanner, dash } from '../Degraded'
import { apiErr } from '../UserModals'

/* What is serving: build, instance, migrations, the timeouts every panel runs
   under, and the scheduler's state. Numbers, names and flags only — the
   server never echoes a secret (api/routes/admin_ops.py::admin_system). */

function Facts({ title, rows }: { title: string; rows: [string, React.ReactNode][] }) {
  return (
    <div style={{ ...CARD, padding: '14px 16px', marginBottom: 0 }}>
      <h2 className="t-eyebrow" style={{ margin: '0 0 8px' }}>{title}</h2>
      <dl style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '5px 16px', margin: 0, fontSize: 13 }}>
        {rows.map(([k, v]) => (
          <Fragment key={k}>
            <dt style={{ color: 'var(--color-ink-500)' }}>{k}</dt>
            <dd style={{ margin: 0, color: 'var(--color-ink-800)', wordBreak: 'break-word' }}>{v}</dd>
          </Fragment>
        ))}
      </dl>
    </div>
  )
}

function seconds(ms: number): string {
  return `${(ms / 1000).toLocaleString()} s`
}

function hourUtc(h: number): string {
  return `${String(h).padStart(2, '0')}:00 UTC`
}

export function OpsSystem({ refreshKey }: { refreshKey: number }) {
  const [data, setData] = useState<AdminSystemInfo | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    adminSystem()
      .then((d) => { if (alive) { setData(d); setError(null) } })
      .catch((e: unknown) => { if (alive) setError(apiErr(e, 'Failed to load system info')) })
    return () => { alive = false }
  }, [refreshKey])

  if (error) return <p style={{ color: 'var(--color-danger)', fontSize: 13 }}>{error}</p>
  if (!data) return <SkeletonCards count={4} columns={2} h={180} gap={12} />

  const m = data.migrations
  const pending = m.pending
  const pendingCell = pending === null
    ? '—'
    : pending.length === 0
      ? <span style={{ color: 'var(--color-moss)' }}>none</span>
      : <span style={{ color: 'var(--color-danger)', fontWeight: 600 }}>{pending.length} pending: {pending.join(', ')}</span>

  return (
    <div>
      <h2 className="t-eyebrow" style={{ margin: '0 0 10px' }}>System</h2>
      <DegradedBanner sources={[{ source: 'System', items: data.degraded }]} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 12 }}>
        <Facts title="Build" rows={[
          ['Commit', data.app.commit ? <code>{data.app.commit.slice(0, 12)}</code> : '— (not set; Render fills RENDER_GIT_COMMIT)'],
          ['Service', data.app.service ?? '—'],
          ['Instance', data.app.instance_id ?? '—'],
          ['Host', data.app.host],
          ['Python', data.app.python],
          ['Postgres', data.app.postgres ?? '—'],
        ]} />
        <Facts title="Migrations" rows={[
          ['Applied', `${dash(m.applied)} of ${m.on_disk} on disk`],
          ['Pending', pendingCell],
          ['Latest', m.latest_applied ? `${m.latest_applied.filename} · ${fmtDateTime(m.latest_applied.applied_at)}` : '—'],
        ]} />
        <Facts title="Database" rows={[
          ['Pool', `${data.db.pool_min}–${data.db.pool_max} connections per instance`],
          ['Statement timeout', seconds(data.db.statement_timeout_ms)],
          ['Dashboard panel cap', seconds(data.db.dashboard_statement_timeout_ms)],
          ['Account delete', seconds(data.db.account_delete_timeout_ms)],
          ['Data-health block', seconds(data.db.data_health_block_timeout_ms)],
        ]} />
        <Facts title="Scheduler" rows={[
          ['State', data.scheduler.running
            ? <span style={{ color: 'var(--color-moss)' }}>running</span>
            : <span style={{ color: 'var(--color-danger)' }}>stopped</span>],
          ['Jobs registered', String(data.scheduler.jobs)],
          ['Daily ticks', hourUtc(data.scheduler.workflow_tick_hour)],
          ['User digest', hourUtc(data.scheduler.user_digest_hour)],
          ['ML retrain', data.scheduler.ml_retrain_enabled ? 'enabled' : 'disabled'],
          ['Run watchdog', data.scheduler.run_max_seconds ? `${data.scheduler.run_max_seconds.toLocaleString()} s` : 'off'],
        ]} />
      </div>
    </div>
  )
}
