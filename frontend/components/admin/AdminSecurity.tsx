'use client'
import { Skeleton, SkeletonRows, EmptyRow } from '@/components/ds'
import { useCallback, useEffect, useRef, useState } from 'react'
import { adminAuthEvents, adminSecurity } from '@/lib/api'
import type { AdminSecurityReport, AuthEventRow, ConfigCheck } from '@/lib/types'
import { TH_STYLE, TD_STYLE, zebra, fmtDate, fmtDateTime, Pagination } from './AdminTable'

const CARD: React.CSSProperties = {
  background: 'var(--color-surface)', borderRadius: 'var(--radius-card)',
  boxShadow: 'var(--shadow-card)', marginBottom: 18,
}

const CHECK_COLOR: Record<ConfigCheck['status'], string> = {
  ok: 'var(--color-success)',
  warn: 'var(--color-warning)',
  error: 'var(--color-danger)',
  info: 'var(--color-ink-400)',
}

function SectionTable({ title, headers, empty, children }: {
  title: string
  headers: string[]
  empty: boolean
  children: React.ReactNode
}) {
  return (
    <div style={{ ...CARD, overflowX: 'auto' }}>
      <h2 className="t-eyebrow" style={{ margin: 0, padding: '14px 16px 8px' }}>{title}</h2>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>{headers.map((h) => <th key={h} style={TH_STYLE}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {empty && (
            <tr><td colSpan={headers.length} style={{ ...TD_STYLE, textAlign: 'center', padding: '24px 0', color: 'var(--color-ink-400)' }}>Nothing to show</td></tr>
          )}
          {children}
        </tbody>
      </table>
    </div>
  )
}

export function AdminSecurity() {
  const [report, setReport] = useState<AdminSecurityReport | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [events, setEvents] = useState<AuthEventRow[]>([])
  const [eventsTotal, setEventsTotal] = useState(0)
  const [eventsLoaded, setEventsLoaded] = useState(false)
  const [successFilter, setSuccessFilter] = useState('')
  const [methodFilter, setMethodFilter] = useState('')
  const [ipFilter, setIpFilter] = useState('')
  const [page, setPage] = useState(1)
  const pageSize = 50
  // Monotonic request id: a slow filtered query resolving after a newer one
  // must not overwrite the newer rows (the debounce only cancels un-fired timers).
  const reqRef = useRef(0)

  useEffect(() => {
    adminSecurity().then(setReport).catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load'))
  }, [])

  const loadEvents = useCallback(async () => {
    const reqId = ++reqRef.current
    try {
      const p = await adminAuthEvents({
        success: successFilter === '' ? undefined : successFilter === 'true',
        method: methodFilter || undefined,
        ip: ipFilter || undefined,
        page, page_size: pageSize,
      })
      if (reqId !== reqRef.current) return
      setEvents(p.items)
      setEventsTotal(p.total)
      setEventsLoaded(true)
    } catch { /* feed is best-effort; report above still renders */ }
  }, [successFilter, methodFilter, ipFilter, page])

  useEffect(() => {
    const t = setTimeout(loadEvents, ipFilter ? 300 : 0)
    return () => clearTimeout(t)
  }, [loadEvents, ipFilter])

  if (error) return <p style={{ color: 'var(--color-danger)', fontSize: 13 }}>{error}</p>
  if (!report) return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Skeleton h={140} radius="var(--radius-card)" />
      <Skeleton h={220} radius="var(--radius-card)" />
    </div>
  )

  return (
    <div>
      {/* ── Config checks ── */}
      <div style={{ ...CARD, padding: '6px 16px' }}>
        <h2 className="t-eyebrow" style={{ margin: 0, padding: '10px 0 6px' }}>Configuration checks</h2>
        {report.config_checks.map((c) => (
          <div key={c.key} style={{ display: 'flex', alignItems: 'flex-start', gap: 10, padding: '9px 0', borderBottom: '1px solid var(--color-ink-100)' }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: CHECK_COLOR[c.status], flexShrink: 0, marginTop: 5 }} />
            <div style={{ flex: 1 }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-ink-900)' }}>{c.label}</span>
              <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: CHECK_COLOR[c.status], marginLeft: 8 }}>{c.status}</span>
              <p style={{ margin: '2px 0 0', fontSize: 12.5, color: 'var(--color-ink-500)', lineHeight: 1.5 }}>{c.detail}</p>
            </div>
          </div>
        ))}
        <p style={{ margin: 0, padding: '9px 0', fontSize: 12, color: 'var(--color-ink-400)' }}>
          Reset tokens outstanding: {report.reset_tokens.live} live · {report.reset_tokens.stale_unused} expired-unused
        </p>
      </div>

      {/* ── Failed logins ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 18 }}>
        <SectionTable title="Failed logins by IP · 24h" headers={['IP', 'Attempts', 'Identifiers', 'Last']} empty={report.failed_by_ip.length === 0}>
          {report.failed_by_ip.map((r, i) => (
            <tr key={r.ip ?? i} style={{ background: zebra(i) }}>
              <td style={TD_STYLE} className="tabular">{r.ip ?? '—'}</td>
              <td style={TD_STYLE} className="tabular">{r.attempts}</td>
              <td style={TD_STYLE} className="tabular">{r.identifiers}</td>
              <td style={TD_STYLE}>{fmtDateTime(r.last_at)}</td>
            </tr>
          ))}
        </SectionTable>
        <SectionTable title="Failed logins by identifier · 24h" headers={['Identifier', 'Attempts', 'IPs', 'Last']} empty={report.failed_by_identifier.length === 0}>
          {report.failed_by_identifier.map((r, i) => (
            <tr key={r.attempted_identifier ?? i} style={{ background: zebra(i) }}>
              <td style={TD_STYLE}>{r.attempted_identifier ?? '—'}</td>
              <td style={TD_STYLE} className="tabular">{r.attempts}</td>
              <td style={TD_STYLE} className="tabular">{r.ips}</td>
              <td style={TD_STYLE}>{fmtDateTime(r.last_at)}</td>
            </tr>
          ))}
        </SectionTable>
      </div>

      {/* ── User hygiene ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 18 }}>
        <SectionTable title="Unverified users (older than 3 days)" headers={['User', 'Org', 'Signed up']} empty={report.unverified_users.length === 0}>
          {report.unverified_users.map((u, i) => (
            <tr key={u.id} style={{ background: zebra(i) }}>
              <td style={TD_STYLE}>{u.username} <span style={{ color: 'var(--color-ink-400)', fontSize: 12 }}>{u.email}</span></td>
              <td style={TD_STYLE}>{u.account_name}</td>
              <td style={TD_STYLE}>{fmtDate(u.created_at)}</td>
            </tr>
          ))}
        </SectionTable>
        <SectionTable title="Disabled users" headers={['User', 'Org', 'Created']} empty={report.disabled_users.length === 0}>
          {report.disabled_users.map((u, i) => (
            <tr key={u.id} style={{ background: zebra(i) }}>
              <td style={TD_STYLE}>{u.username} <span style={{ color: 'var(--color-ink-400)', fontSize: 12 }}>{u.email}</span></td>
              <td style={TD_STYLE}>{u.account_name}</td>
              <td style={TD_STYLE}>{fmtDate(u.created_at)}</td>
            </tr>
          ))}
        </SectionTable>
      </div>

      {/* ── Integration failures ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 18 }}>
        <SectionTable title="Stripe webhook errors" headers={['Event', 'Error', 'Received']} empty={report.webhook_errors.length === 0}>
          {report.webhook_errors.map((w, i) => (
            <tr key={w.id} style={{ background: zebra(i) }}>
              <td style={TD_STYLE}>{w.event_type}</td>
              <td style={{ ...TD_STYLE, maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis' }} title={w.error ?? ''}>{w.error ?? '—'}</td>
              <td style={TD_STYLE}>{fmtDateTime(w.received_at)}</td>
            </tr>
          ))}
        </SectionTable>
        <SectionTable title="Pipeline failures · 7d" headers={['Run', 'Org', 'Status', 'When']} empty={report.pipeline_failures.length === 0}>
          {report.pipeline_failures.map((r, i) => (
            <tr key={r.id} style={{ background: zebra(i) }}>
              <td style={TD_STYLE}>#{r.id} · {r.zip}{r.error ? ` (${r.error})` : ''}</td>
              <td style={TD_STYLE}>{r.account_name ?? '—'}</td>
              <td style={{ ...TD_STYLE, color: 'var(--color-danger)' }}>{r.status}</td>
              <td style={TD_STYLE}>{fmtDateTime(r.created_at)}</td>
            </tr>
          ))}
        </SectionTable>
      </div>

      {/* ── Auth events feed ── */}
      <div style={{ ...CARD, overflowX: 'auto' }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '14px 16px 6px', flexWrap: 'wrap' }}>
          <h2 className="t-eyebrow" style={{ margin: 0, marginRight: 'auto' }}>Auth events</h2>
          <select className="select-field" value={successFilter} onChange={(e) => { setSuccessFilter(e.target.value); setPage(1) }}>
            <option value="">All outcomes</option>
            <option value="true">Success</option>
            <option value="false">Failure</option>
          </select>
          <select className="select-field" value={methodFilter} onChange={(e) => { setMethodFilter(e.target.value); setPage(1) }}>
            <option value="">All methods</option>
            <option value="password">password</option>
            <option value="google">google</option>
            <option value="apple">apple</option>
          </select>
          <input className="drawer-input" placeholder="Filter by IP" value={ipFilter} onChange={(e) => { setIpFilter(e.target.value); setPage(1) }} style={{ width: 140 }} />
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={TH_STYLE}>When</th>
              <th style={TH_STYLE}>Identifier</th>
              <th style={TH_STYLE}>User</th>
              <th style={TH_STYLE}>Org</th>
              <th style={TH_STYLE}>Method</th>
              <th style={TH_STYLE}>Outcome</th>
              <th style={TH_STYLE}>IP</th>
            </tr>
          </thead>
          <tbody>
            {events.length === 0 && (
              eventsLoaded
                ? <EmptyRow colSpan={7} size="sm" title="No sign-in events" hint="Successful and failed logins appear here as they happen." />
                : <SkeletonRows rows={5} cols={7} />
            )}
            {events.map((ev, i) => (
              <tr key={ev.id} style={{ background: zebra(i) }}>
                <td style={TD_STYLE}>{fmtDateTime(ev.created_at)}</td>
                <td style={TD_STYLE}>{ev.attempted_identifier ?? '—'}</td>
                <td style={TD_STYLE}>{ev.username ?? '—'}</td>
                <td style={TD_STYLE}>{ev.account_name ?? '—'}</td>
                <td style={TD_STYLE}>{ev.method}</td>
                <td style={{ ...TD_STYLE, color: ev.success ? 'var(--color-moss)' : 'var(--color-danger)' }}>
                  {ev.success ? 'success' : ev.failure_reason ?? 'failed'}
                </td>
                <td style={TD_STYLE} className="tabular">{ev.ip ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ padding: '0 10px' }}>
          <Pagination total={eventsTotal} page={page} pageSize={pageSize} noun="events" onPage={setPage} />
        </div>
      </div>
    </div>
  )
}
