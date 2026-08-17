'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Search } from 'lucide-react'
import { adminAccounts } from '@/lib/api'
import type { AdminAccountRow } from '@/lib/types'
import { TH_STYLE, TD_STYLE, zebra, fmtDate, fmtDateTime, Pagination } from './AdminTable'

const PLAN_OPTIONS = ['', 'starter', 'growth', 'pro']
const STATUS_OPTIONS = ['', 'trialing', 'trial_expired', 'active', 'past_due', 'canceled']

const STATUS_COLOR: Record<string, string> = {
  trialing: 'var(--color-gold)',
  trial_expired: 'var(--color-danger)',
  active: 'var(--color-moss)',
  past_due: 'var(--color-warning)',
  canceled: 'var(--color-ink-400)',
}

export function AdminOrgs() {
  const router = useRouter()
  const [rows, setRows] = useState<AdminAccountRow[]>([])
  const [total, setTotal] = useState(0)
  const [q, setQ] = useState('')
  const [plan, setPlan] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const pageSize = 50

  // Monotonic request id: a slow filtered query resolving after a newer one
  // must not overwrite the newer rows (the debounce only cancels un-fired timers).
  const reqRef = useRef(0)

  const load = useCallback(async (query: string, planF: string, statusF: string, pageNo: number) => {
    const reqId = ++reqRef.current
    setLoading(true)
    setError(null)
    try {
      const p = await adminAccounts({ q: query || undefined, plan: planF || undefined, billing_status: statusF || undefined, page: pageNo, page_size: pageSize })
      if (reqId !== reqRef.current) return
      setRows(p.items)
      setTotal(p.total)
    } catch (e: unknown) {
      if (reqId !== reqRef.current) return
      setError(e instanceof Error ? e.message : 'Failed to load orgs')
    } finally {
      if (reqId === reqRef.current) setLoading(false)
    }
  }, [])

  // 300ms debounce on the search box; filter changes reset to page 1.
  useEffect(() => {
    const t = setTimeout(() => load(q, plan, status, page), q ? 300 : 0)
    return () => clearTimeout(t)
  }, [q, plan, status, page, load])

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 14, flexWrap: 'wrap' }}>
        <div style={{ position: 'relative', flex: '1 1 220px', maxWidth: 320 }}>
          <Search size={13} strokeWidth={1.5} color="var(--color-ink-400)" style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)' }} />
          <input
            className="drawer-input"
            placeholder="Search orgs by name or id…"
            value={q}
            onChange={(e) => { setQ(e.target.value); setPage(1) }}
            style={{ width: '100%', paddingLeft: 30 }}
          />
        </div>
        <select className="select-field" value={plan} onChange={(e) => { setPlan(e.target.value); setPage(1) }}>
          {PLAN_OPTIONS.map((p) => <option key={p} value={p}>{p || 'Any plan'}</option>)}
        </select>
        <select className="select-field" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}>
          {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s || 'Any billing status'}</option>)}
        </select>
      </div>

      {error && <p style={{ color: 'var(--color-danger)', fontSize: 13 }}>{error}</p>}

      <div style={{ background: 'var(--color-surface)', borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)', overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={TH_STYLE}>Org</th>
              <th style={TH_STYLE}>Type</th>
              <th style={TH_STYLE}>Plan</th>
              <th style={TH_STYLE}>Billing</th>
              <th style={TH_STYLE}>Users</th>
              <th style={TH_STYLE}>Leads</th>
              <th style={TH_STYLE}>Last activity</th>
              <th style={TH_STYLE}>Created</th>
            </tr>
          </thead>
          <tbody>
            {loading && rows.length === 0 && (
              <tr><td colSpan={8} style={{ ...TD_STYLE, textAlign: 'center', padding: '48px 0', color: 'var(--color-ink-400)' }}>Loading…</td></tr>
            )}
            {!loading && rows.length === 0 && (
              <tr><td colSpan={8} style={{ ...TD_STYLE, textAlign: 'center', padding: '48px 0', color: 'var(--color-ink-400)' }}>No orgs match</td></tr>
            )}
            {rows.map((r, i) => (
              <tr
                key={r.id}
                onClick={() => router.push(`/admin/orgs/${r.id}`)}
                style={{ background: zebra(i), cursor: 'pointer' }}
                onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--color-surface-hi)' }}
                onMouseLeave={(e) => { e.currentTarget.style.background = zebra(i) }}
              >
                <td style={TD_STYLE}>
                  <span style={{ fontWeight: 600, color: 'var(--color-ink-900)' }}>{r.name}</span>
                  <span style={{ color: 'var(--color-ink-400)', marginLeft: 6, fontSize: 12 }}>#{r.id}</span>
                </td>
                <td style={TD_STYLE}>{r.business_type}</td>
                <td style={TD_STYLE}>{r.plan_name ?? '—'}</td>
                <td style={TD_STYLE}>
                  {r.billing_status ? (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, color: STATUS_COLOR[r.billing_status] ?? 'var(--color-ink-600)', fontSize: 12.5, fontWeight: 500 }}>
                      <span style={{ width: 6, height: 6, borderRadius: '50%', background: STATUS_COLOR[r.billing_status] ?? 'var(--color-ink-400)' }} />
                      {r.billing_status}
                      {r.billing_status === 'trialing' && r.trial_ends_at && (
                        <span style={{ color: 'var(--color-ink-400)' }}>→ {fmtDate(r.trial_ends_at)}</span>
                      )}
                    </span>
                  ) : '—'}
                </td>
                <td style={TD_STYLE} className="tabular">{r.users_active}/{r.users_total}</td>
                <td style={TD_STYLE} className="tabular">{r.lead_count.toLocaleString()}</td>
                <td style={TD_STYLE}>{fmtDateTime(r.last_activity_at)}</td>
                <td style={TD_STYLE}>{fmtDate(r.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination total={total} page={page} pageSize={pageSize} noun="orgs" onPage={setPage} />
    </div>
  )
}
