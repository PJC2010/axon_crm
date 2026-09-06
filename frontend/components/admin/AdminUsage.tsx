'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { adminUsage } from '@/lib/api'
import type { AdminUsagePage, AdminUsageRow } from '@/lib/types'
import { SkeletonRows, EmptyRow } from '@/components/ds'
import { TH_STYLE, TD_STYLE, zebra, Pagination } from './AdminTable'
import { DegradedBanner, dash } from './Degraded'

/* What each tenant costs the platform. Every metric column can be "—" when
   its query was cut off (the banner names it); sorting puts those last. */

type MetricKey = Exclude<keyof AdminUsageRow, 'account_id' | 'name' | 'plan_name' | 'scoring_limit'>

const COLUMNS: { key: MetricKey; label: string; title: string }[] = [
  { key: 'rentcast_requests', label: 'RentCast', title: 'Billable RentCast requests in the window (prospect pulls)' },
  { key: 'scoring_reveals', label: 'Reveals', title: 'Scored-lead reveals this calendar month, against the effective limit' },
  { key: 'runs', label: 'Runs', title: 'Completed pipeline runs in the window' },
  { key: 'skip_traces', label: 'Skip traces', title: 'Paid skip-trace lookups reported by those runs' },
  { key: 'sms_sent', label: 'SMS', title: 'Outbound SMS in the window' },
  { key: 'email_sent', label: 'Email', title: 'Outbound lead emails in the window' },
  { key: 'calls', label: 'Calls', title: 'Calls in the window' },
  { key: 'call_minutes', label: 'Call min', title: 'Call minutes in the window' },
  { key: 'tracking_numbers_active', label: 'Twilio #s', title: 'Active tracking numbers — each is a recurring charge' },
  { key: 'territories', label: 'ZIPs run', title: 'Distinct ZIPs the pipeline ran in the window' },
]

export function AdminUsage() {
  const [days, setDays] = useState(30)
  const [sort, setSort] = useState<string>('name')
  const [page, setPage] = useState(1)
  const [result, setResult] = useState<{ key: string; page: AdminUsagePage } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pageSize = 50
  const key = `${days}|${sort}|${page}`

  // The response is stored with the filter key it answered, so a slow query
  // resolving after a newer one renders as loading, never as the wrong rows;
  // the alive flag drops it entirely once the filters have moved on.
  useEffect(() => {
    let alive = true
    adminUsage({ days, sort, page, page_size: pageSize })
      .then((p) => { if (alive) { setResult({ key, page: p }); setError(null) } })
      .catch((e: unknown) => { if (alive) setError(e instanceof Error ? e.message : 'Failed to load usage') })
    return () => { alive = false }
  }, [key, days, sort, page])

  const current = result?.key === key ? result.page : null
  const rows: AdminUsageRow[] = current?.items ?? []
  const total = current?.total ?? 0
  const degraded = current?.degraded ?? []
  const loading = !current && !error

  function sortBy(key: string) {
    setSort(key)
    setPage(1)
  }

  const sortable = (key: string, label: string, title?: string) => (
    <th
      key={key}
      title={title}
      aria-sort={sort === key ? (key === 'name' ? 'ascending' : 'descending') : 'none'}
      style={{ ...TH_STYLE, cursor: 'pointer', color: sort === key ? 'var(--color-accent-300)' : TH_STYLE.color }}
      onClick={() => sortBy(key)}
    >
      {label}{sort === key ? (key === 'name' ? ' ↑' : ' ↓') : ''}
    </th>
  )

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 14, flexWrap: 'wrap' }}>
        <select className="select-field" value={days} onChange={(e) => { setDays(Number(e.target.value)); setPage(1) }}>
          {[7, 30, 90].map((d) => <option key={d} value={d}>Last {d} days</option>)}
        </select>
        <span style={{ fontSize: 12.5, color: 'var(--color-ink-400)' }}>
          Click a column to rank orgs by it. Reveals count the current calendar month; Twilio numbers are active now.
        </span>
      </div>

      <DegradedBanner sources={[{ source: 'Usage', items: degraded }]} />
      {error && <p style={{ color: 'var(--color-danger)', fontSize: 13 }}>{error}</p>}

      <div style={{ background: 'var(--color-surface)', borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)', overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              {sortable('name', 'Org')}
              <th style={TH_STYLE}>Plan</th>
              {COLUMNS.map((c) => sortable(c.key, c.label, c.title))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && loading && <SkeletonRows rows={6} cols={COLUMNS.length + 2} />}
            {rows.length === 0 && !loading && (
              <EmptyRow colSpan={COLUMNS.length + 2} size="sm" title="No organizations yet" hint="Usage appears here once an org exists." />
            )}
            {rows.map((r, i) => (
              <tr key={r.account_id} style={{ background: zebra(i) }}>
                <td style={TD_STYLE}>
                  <Link href={`/admin/orgs/${r.account_id}`} style={{ fontWeight: 600, color: 'var(--color-ink-900)', textDecoration: 'none' }}>{r.name}</Link>
                  <span style={{ color: 'var(--color-ink-400)', marginLeft: 6, fontSize: 12 }}>#{r.account_id}</span>
                </td>
                <td style={TD_STYLE}>{r.plan_name ?? '—'}</td>
                {COLUMNS.map((c) => (
                  <td key={c.key} style={TD_STYLE} className="tabular">
                    {c.key === 'scoring_reveals'
                      ? <>{dash(r.scoring_reveals)} <span style={{ color: 'var(--color-ink-400)' }}>/ {r.scoring_limit === null ? '∞' : r.scoring_limit.toLocaleString()}</span></>
                      : dash(r[c.key])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination total={total} page={page} pageSize={pageSize} noun="orgs" onPage={setPage} />
    </div>
  )
}
