'use client'
import { Fragment, useEffect, useState } from 'react'
import Link from 'next/link'
import { adminAccounts, adminCancelRun, adminRun, adminRuns } from '@/lib/api'
import type { AdminAccountRow, AdminPage, AdminRunDetail, AdminRunRow } from '@/lib/types'
import { SkeletonRows, EmptyRow } from '@/components/ds'
import { ConfirmModal } from '@/components/ConfirmModal'
import { TH_STYLE, TD_STYLE, zebra, fmtDateTime, fmtDuration, Pagination, CARD } from '../AdminTable'
import { dash } from '../Degraded'
import { Modal, apiErr } from '../UserModals'

/* Every org's pipeline runs, newest first — what is queued or running right
   now across the platform, and what failed. Cancel is the platform twin of the
   tenant's: the row flips to cancelled at once and the run stops between steps
   on the instance executing it; a run on the other instance never sees the
   flag (api/routes/admin_ops.py::admin_cancel_run). */

const STATUSES = ['queued', 'running', 'done', 'failed', 'cancelled']
const TRIGGERS = ['schedule', 'manual', 'zip_sample']
const PAGE_SIZE = 50

const STATUS_COLOR: Record<string, string> = {
  queued: 'var(--color-ink-500)',
  running: 'var(--color-gold)',
  done: 'var(--color-moss)',
  failed: 'var(--color-danger)',
  cancelled: 'var(--color-ink-500)',
}

const HEADERS = ['Run', 'Org', 'ZIP', 'Vertical', 'Status', 'Trigger', 'Created', 'Duration', 'Scored', 'Error', '']

type Detail = { id: number; run?: AdminRunDetail; error?: string }

export function OpsRuns({ refreshKey, onToast }: {
  refreshKey: number
  onToast: (message: string, variant?: 'success' | 'error') => void
}) {
  const [status, setStatus] = useState('')
  const [trigger, setTrigger] = useState('')
  const [org, setOrg] = useState('')
  const [zipInput, setZipInput] = useState('')
  const [zip, setZip] = useState('')
  const [page, setPage] = useState(1)
  const [tick, setTick] = useState(0)
  const [result, setResult] = useState<{ key: string; page: AdminPage<AdminRunRow> } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [orgs, setOrgs] = useState<AdminAccountRow[]>([])
  const [detail, setDetail] = useState<Detail | null>(null)
  const [cancelTarget, setCancelTarget] = useState<AdminRunRow | null>(null)
  const [cancelling, setCancelling] = useState(false)
  const key = `${status}|${trigger}|${org}|${zip}|${page}|${refreshKey}|${tick}`

  // The ZIP box is debounced into the filter; the selects apply at once.
  useEffect(() => {
    const t = setTimeout(() => setZip(zipInput.trim()), zipInput ? 300 : 0)
    return () => clearTimeout(t)
  }, [zipInput])

  useEffect(() => {
    let alive = true
    adminAccounts({ page_size: 100, sort: 'name' })
      .then((p) => { if (alive) setOrgs(p.items) })
      .catch(() => { /* the org select just stays empty */ })
    return () => { alive = false }
  }, [])

  // The response is stored with the filter key it answered, so a slow query
  // resolving after a newer one renders as loading, never as the wrong rows.
  useEffect(() => {
    let alive = true
    adminRuns({
      status: status || undefined,
      triggered_by: trigger || undefined,
      account_id: org ? Number(org) : undefined,
      zip: zip || undefined,
      page,
      page_size: PAGE_SIZE,
    })
      .then((p) => { if (alive) { setResult({ key, page: p }); setError(null) } })
      .catch((e: unknown) => { if (alive) setError(apiErr(e, 'Failed to load runs')) })
    return () => { alive = false }
  }, [key, status, trigger, org, zip, page])

  const current = result?.key === key ? result.page : null
  const rows = current?.items ?? []
  const total = current?.total ?? 0
  const loading = !current && !error

  function resetPage() { setPage(1) }

  function openDetail(id: number) {
    setDetail({ id })
    adminRun(id)
      .then((r) => setDetail((d) => (d && d.id === id ? { id, run: r } : d)))
      .catch((e: unknown) => setDetail((d) => (d && d.id === id ? { id, error: apiErr(e, 'Failed to load the run') } : d)))
  }

  async function confirmCancel() {
    if (!cancelTarget) return
    setCancelling(true)
    try {
      const r = await adminCancelRun(cancelTarget.id)
      onToast(`Run #${r.run_id} cancelled (was ${r.previous_status})`)
      setCancelTarget(null)
      setTick((t) => t + 1)
    } catch (e: unknown) {
      onToast(apiErr(e, 'Could not cancel the run'), 'error')
    } finally {
      setCancelling(false)
    }
  }

  const facts: [string, string][] = detail?.run ? [
    ['Org', detail.run.account_name ?? `#${detail.run.account_id}`],
    ['ZIP', detail.run.zip ?? '—'],
    ['Vertical', detail.run.vertical ?? '—'],
    ['Status', detail.run.status],
    ['Trigger', `${detail.run.triggered_by ?? '—'}${detail.run.schedule_id ? ` (schedule #${detail.run.schedule_id})` : ''}`],
    ['Created', fmtDateTime(detail.run.created_at)],
    ['Started', fmtDateTime(detail.run.started_at)],
    ['Finished', fmtDateTime(detail.run.finished_at)],
  ] : []

  return (
    <div style={{ marginBottom: 22 }}>
      <div style={{ ...CARD, overflowX: 'auto', marginBottom: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', padding: '14px 16px 10px' }}>
          <h2 className="t-eyebrow" style={{ margin: 0, marginRight: 6 }}>Pipeline runs</h2>
          <select className="select-field" value={status} onChange={(e) => { setStatus(e.target.value); resetPage() }}>
            <option value="">Any status</option>
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select className="select-field" value={trigger} onChange={(e) => { setTrigger(e.target.value); resetPage() }}>
            <option value="">Any trigger</option>
            {TRIGGERS.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          <select className="select-field" value={org} onChange={(e) => { setOrg(e.target.value); resetPage() }}>
            <option value="">All orgs</option>
            {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
          <input className="drawer-input" placeholder="ZIP" value={zipInput}
            onChange={(e) => { setZipInput(e.target.value); resetPage() }} style={{ width: 110 }} />
          <span style={{ fontSize: 12, color: 'var(--color-ink-400)' }}>Click a row for its result JSON.</span>
        </div>
        {error && <p style={{ color: 'var(--color-danger)', fontSize: 13, padding: '0 16px 10px', margin: 0 }}>{error}</p>}
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>{HEADERS.map((h, i) => <th key={`${h}-${i}`} style={TH_STYLE}>{h}</th>)}</tr>
          </thead>
          <tbody>
            {rows.length === 0 && loading && <SkeletonRows rows={6} cols={HEADERS.length} />}
            {rows.length === 0 && !loading && (
              <EmptyRow colSpan={HEADERS.length} size="sm" title="No runs match" hint="Runs appear here as soon as any org's pipeline is queued." />
            )}
            {rows.map((r, i) => (
              <tr key={r.id} style={{ background: zebra(i), cursor: 'pointer' }} onClick={() => openDetail(r.id)}>
                <td style={TD_STYLE} className="tabular">#{r.id}</td>
                <td style={TD_STYLE}>
                  <Link href={`/admin/orgs/${r.account_id}`} onClick={(e) => e.stopPropagation()}
                    style={{ fontWeight: 600, color: 'var(--color-ink-900)', textDecoration: 'none' }}>
                    {r.account_name ?? `Org #${r.account_id}`}
                  </Link>
                </td>
                <td style={TD_STYLE}>{r.zip ?? '—'}</td>
                <td style={TD_STYLE}>{r.vertical ?? '—'}</td>
                <td style={TD_STYLE}>
                  <span style={{ color: STATUS_COLOR[r.status] ?? 'var(--color-ink-700)', fontWeight: 500 }}>{r.status}</span>
                </td>
                <td style={TD_STYLE}>
                  {r.triggered_by ?? '—'}
                  {r.schedule_id !== null && <span style={{ color: 'var(--color-ink-400)', marginLeft: 4, fontSize: 12 }}>#{r.schedule_id}</span>}
                </td>
                <td style={TD_STYLE}>{fmtDateTime(r.created_at)}</td>
                <td style={TD_STYLE} className="tabular">{fmtDuration(r.duration_seconds)}</td>
                <td style={TD_STYLE} className="tabular">{dash(r.properties_scored)}</td>
                <td title={r.error ?? undefined}
                  style={{ ...TD_STYLE, maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: r.error ? 'var(--color-danger)' : TD_STYLE.color }}>
                  {r.error ?? ''}
                </td>
                <td style={{ ...TD_STYLE, textAlign: 'right', whiteSpace: 'nowrap' }}>
                  {(r.status === 'queued' || r.status === 'running') && (
                    <button className="btn-secondary" style={{ fontSize: 12, padding: '3px 9px' }}
                      onClick={(e) => { e.stopPropagation(); setCancelTarget(r) }}>
                      Cancel
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination total={total} page={page} pageSize={PAGE_SIZE} noun="runs" onPage={setPage} />

      {detail && (
        <Modal title={`Run #${detail.id}`} onClose={() => setDetail(null)} width={640}>
          {!detail.run && !detail.error && <p style={{ margin: 0, fontSize: 13, color: 'var(--color-ink-400)' }}>Loading…</p>}
          {detail.error && <p style={{ margin: 0, fontSize: 13, color: 'var(--color-danger)' }}>{detail.error}</p>}
          {detail.run && (
            <>
              <dl style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '4px 14px', fontSize: 13, margin: '0 0 12px' }}>
                {facts.map(([k, v]) => (
                  <Fragment key={k}>
                    <dt style={{ color: 'var(--color-ink-500)' }}>{k}</dt>
                    <dd style={{ margin: 0, color: 'var(--color-ink-800)' }}>{v}</dd>
                  </Fragment>
                ))}
              </dl>
              <p className="t-eyebrow" style={{ margin: '0 0 6px' }}>result_json</p>
              <pre style={{
                margin: 0, padding: 12, background: 'var(--color-paper)', borderRadius: 'var(--radius-card)',
                fontSize: 12, lineHeight: 1.45, maxHeight: 360, overflow: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              }}>
                {detail.run.result_json ? JSON.stringify(detail.run.result_json, null, 2) : 'null'}
              </pre>
            </>
          )}
        </Modal>
      )}

      {cancelTarget && (
        <ConfirmModal
          title={`Cancel run #${cancelTarget.id}?`}
          message={`${cancelTarget.account_name ?? `Org #${cancelTarget.account_id}`} · ZIP ${cancelTarget.zip ?? '—'} · ${cancelTarget.status}. The row is marked cancelled now and the run stops between steps on the instance running it. A run on another instance keeps going and may overwrite the status when it finishes.`}
          confirmLabel="Cancel run"
          danger
          loading={cancelling}
          onConfirm={confirmCancel}
          onCancel={() => setCancelTarget(null)}
        />
      )}
    </div>
  )
}
