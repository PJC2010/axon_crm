'use client'
import { Fragment, useEffect, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { adminJobRuns, adminJobs } from '@/lib/api'
import type { AdminJobRow, AdminJobRunRow, AdminJobsReport, JobRunStatus } from '@/lib/types'
import { SkeletonRows } from '@/components/ds'
import { TH_STYLE, TD_STYLE, zebra, fmtDateTime, fmtDuration, SectionTable } from '../AdminTable'
import { DegradedBanner } from '../Degraded'
import { apiErr } from '../UserModals'

/* Every APScheduler job on the instance that answered, joined with the job
   ledger (scheduler_job_runs, migration 0088). The registry is per process —
   the other instance of the deploy keeps its own — so next-run times are that
   instance's; the ledger's host column says who actually ran a tick. */

const STATUS_COLOR: Record<JobRunStatus, string> = {
  ok: 'var(--color-moss)',
  error: 'var(--color-danger)',
  skipped: 'var(--color-ink-400)',
  running: 'var(--color-gold)',
}

const KIND_LABEL: Record<AdminJobRow['kind'], string> = {
  tick: 'Tick',
  pipeline_schedule: 'Schedule',
  one_shot: 'One-off run',
  geo_rescore_customer: 'Geo rescore',
  unknown: 'Unknown',
}

const SUB_TD: React.CSSProperties = { ...TD_STYLE, padding: '6px 10px', fontSize: 12.5 }

function StatusDot({ status }: { status: JobRunStatus }) {
  return (
    <span title={status} style={{
      display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
      background: STATUS_COLOR[status] ?? 'var(--color-ink-400)', marginRight: 6, verticalAlign: 'middle',
    }} />
  )
}

/** "downgraded=3 · sent=12" out of a run's detail JSON, capped for a cell. */
function detailText(detail: Record<string, unknown> | null | undefined, max = 90): string {
  if (!detail) return ''
  const text = Object.entries(detail)
    .filter(([, v]) => v !== null && v !== undefined && typeof v !== 'object')
    .map(([k, v]) => `${k}=${String(v)}`)
    .join(' · ')
  return text.length > max ? `${text.slice(0, max - 1)}…` : text
}

function kindText(j: AdminJobRow): string {
  if (j.ref !== null && (j.kind === 'pipeline_schedule' || j.kind === 'one_shot')) return `${KIND_LABEL[j.kind]} #${j.ref}`
  return KIND_LABEL[j.kind]
}

type History = { rows?: AdminJobRunRow[]; total?: number; error?: string }

const HEADERS = ['', 'Job', 'Kind', 'Trigger', 'Next run', 'Last run', '7 days']

export function OpsJobs({ refreshKey }: { refreshKey: number }) {
  const [report, setReport] = useState<AdminJobsReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [history, setHistory] = useState<Record<string, History>>({})

  useEffect(() => {
    let alive = true
    adminJobs()
      .then((r) => { if (alive) { setReport(r); setError(null); setHistory({}) } })
      .catch((e: unknown) => { if (alive) setError(apiErr(e, 'Failed to load jobs')) })
    return () => { alive = false }
  }, [refreshKey])

  function toggle(jobId: string) {
    if (open === jobId) { setOpen(null); return }
    setOpen(jobId)
    if (history[jobId]?.rows) return
    adminJobRuns(jobId, 1, 25)
      .then((p) => setHistory((h) => ({ ...h, [jobId]: { rows: p.items, total: p.total } })))
      .catch((e: unknown) => setHistory((h) => ({ ...h, [jobId]: { error: apiErr(e, 'Failed to load history') } })))
  }

  const jobs = report?.jobs ?? []
  const ledgerUnknown = report?.degraded.includes('ledger_last') ?? false
  const note = report
    ? <>Registry of <strong>{report.instance}</strong> · scheduler {report.scheduler.running ? 'running' : 'stopped'} · next-run times are this instance&apos;s; the ledger&apos;s host says who ran a job.</>
    : undefined

  return (
    <>
      <DegradedBanner sources={[{ source: 'Jobs', items: report?.degraded ?? [] }]} />
      {error && <p style={{ color: 'var(--color-danger)', fontSize: 13 }}>{error}</p>}
      <SectionTable title="Scheduler jobs" headers={HEADERS} empty={!!report && jobs.length === 0} note={note}>
        {!report && !error && <SkeletonRows rows={6} cols={HEADERS.length} />}
        {jobs.map((j, i) => {
          const last = j.last
          const expanded = open === j.id
          const h = history[j.id]
          const counts = j.counts_7d
          return (
            <Fragment key={j.id}>
              <tr style={{ background: zebra(i), cursor: 'pointer' }} onClick={() => toggle(j.id)}>
                <td style={{ ...TD_STYLE, width: 28, paddingRight: 0, color: 'var(--color-ink-400)' }}>
                  {expanded ? <ChevronDown size={14} strokeWidth={1.5} /> : <ChevronRight size={14} strokeWidth={1.5} />}
                </td>
                <td style={TD_STYLE}>
                  <span style={{ fontWeight: 600, color: 'var(--color-ink-900)' }}>{j.id}</span>
                  {!j.tracked && (
                    <span title="Not in the job ledger — this job's record is the pipeline runs table below" style={{ marginLeft: 6, fontSize: 11, color: 'var(--color-ink-400)' }}>via runs</span>
                  )}
                </td>
                <td style={TD_STYLE}>{kindText(j)}</td>
                <td style={{ ...TD_STYLE, fontSize: 12, color: 'var(--color-ink-500)' }}>{j.trigger ?? '—'}</td>
                <td style={TD_STYLE}>
                  {j.scheduled_here
                    ? fmtDateTime(j.next_run_time)
                    : <span style={{ color: 'var(--color-ink-400)', fontStyle: 'italic' }}>not on this instance</span>}
                </td>
                <td style={TD_STYLE}>
                  {last === null && !j.tracked && <span style={{ color: 'var(--color-ink-400)' }}>see runs</span>}
                  {last === null && j.tracked && (ledgerUnknown ? '—' : <span style={{ color: 'var(--color-ink-400)' }}>never ran</span>)}
                  {last !== null && (
                    <>
                      <StatusDot status={last.status} />
                      {fmtDateTime(last.started_at)} · {fmtDuration(last.duration_seconds)}{last.host ? ` · ${last.host}` : ''}
                      {last.error && <div style={{ fontSize: 12, color: 'var(--color-danger)', marginTop: 2 }}>{last.error}</div>}
                      {!last.error && detailText(last.detail) && (
                        <div style={{ fontSize: 12, color: 'var(--color-ink-500)', marginTop: 2 }}>{detailText(last.detail)}</div>
                      )}
                    </>
                  )}
                </td>
                <td style={{ ...TD_STYLE, whiteSpace: 'nowrap' }} className="tabular">
                  {counts === null
                    ? '—'
                    : (
                      <>
                        <span style={{ color: 'var(--color-moss)' }}>{counts.ok} ok</span>
                        {' · '}
                        <span style={{ color: counts.error > 0 ? 'var(--color-danger)' : 'var(--color-ink-400)' }}>{counts.error} err</span>
                        {' · '}
                        <span style={{ color: 'var(--color-ink-400)' }}>{counts.skipped} skip</span>
                        {counts.running > 0 && <span style={{ color: 'var(--color-gold)' }}> · {counts.running} running</span>}
                      </>
                    )}
                </td>
              </tr>
              {expanded && (
                <tr>
                  <td colSpan={HEADERS.length} style={{ ...TD_STYLE, background: 'var(--color-paper)', padding: '8px 14px 12px' }}>
                    {!h && <span style={{ fontSize: 12.5, color: 'var(--color-ink-400)' }}>Loading history…</span>}
                    {h?.error && <span style={{ fontSize: 12.5, color: 'var(--color-danger)' }}>{h.error}</span>}
                    {h?.rows && h.rows.length === 0 && (
                      <span style={{ fontSize: 12.5, color: 'var(--color-ink-400)' }}>
                        {j.tracked ? 'No ledger rows yet.' : 'Not ledgered — this job records itself in the pipeline runs below.'}
                      </span>
                    )}
                    {h?.rows && h.rows.length > 0 && (
                      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                        <thead>
                          <tr>{['Started', 'Status', 'Duration', 'Host', 'Detail'].map((x) => <th key={x} style={{ ...TH_STYLE, padding: '6px 10px' }}>{x}</th>)}</tr>
                        </thead>
                        <tbody>
                          {h.rows.map((r) => (
                            <tr key={r.id}>
                              <td style={SUB_TD}>{fmtDateTime(r.started_at)}</td>
                              <td style={SUB_TD}><StatusDot status={r.status} />{r.status}</td>
                              <td style={SUB_TD} className="tabular">{fmtDuration(r.duration_seconds)}</td>
                              <td style={SUB_TD}>{r.host ?? '—'}</td>
                              <td style={{ ...SUB_TD, color: r.error ? 'var(--color-danger)' : 'var(--color-ink-600)' }}>
                                {r.error ?? (detailText(r.detail, 140) || '—')}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                    {h?.rows && h.total !== undefined && h.total > h.rows.length && (
                      <div style={{ fontSize: 12, color: 'var(--color-ink-400)', marginTop: 6 }}>
                        Showing the newest {h.rows.length} of {h.total.toLocaleString()} runs.
                      </div>
                    )}
                  </td>
                </tr>
              )}
            </Fragment>
          )
        })}
      </SectionTable>
    </>
  )
}
