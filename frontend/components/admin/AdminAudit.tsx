'use client'
import { useCallback, useEffect, useState } from 'react'
import { adminAuditLog } from '@/lib/api'
import type { AdminAuditRow } from '@/lib/types'
import { TH_STYLE, TD_STYLE, zebra, fmtDateTime, Pagination } from './AdminTable'

export function AdminAudit() {
  const [rows, setRows] = useState<AdminAuditRow[]>([])
  const [total, setTotal] = useState(0)
  const [loaded, setLoaded] = useState(false)
  const [action, setAction] = useState('')
  const [page, setPage] = useState(1)
  const [error, setError] = useState<string | null>(null)
  const pageSize = 50

  const load = useCallback(async () => {
    setError(null)
    try {
      const p = await adminAuditLog({ action: action || undefined, page, page_size: pageSize })
      setRows(p.items)
      setTotal(p.total)
      setLoaded(true)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load audit log')
    }
  }, [action, page])

  useEffect(() => { load() }, [load])

  const ACTIONS = [
    '', 'user.create', 'user.update', 'user.reset_link', 'user.set_password',
    'account.create', 'account.plan_set', 'account.trial_extend', 'account.trial_expire',
  ]

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 14 }}>
        <select className="select-field" value={action} onChange={(e) => { setAction(e.target.value); setPage(1) }}>
          {ACTIONS.map((a) => <option key={a} value={a}>{a || 'All actions'}</option>)}
        </select>
      </div>

      {error && <p style={{ color: 'var(--color-danger)', fontSize: 13 }}>{error}</p>}

      <div style={{ background: 'var(--color-surface)', borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)', overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={TH_STYLE}>When</th>
              <th style={TH_STYLE}>Admin</th>
              <th style={TH_STYLE}>Action</th>
              <th style={TH_STYLE}>Target</th>
              <th style={TH_STYLE}>Detail</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={5} style={{ ...TD_STYLE, textAlign: 'center', padding: '48px 0', color: 'var(--color-ink-400)' }}>{loaded ? 'No admin actions recorded yet' : 'Loading…'}</td></tr>
            )}
            {rows.map((r, i) => (
              <tr key={r.id} style={{ background: zebra(i) }}>
                <td style={{ ...TD_STYLE, whiteSpace: 'nowrap' }}>{fmtDateTime(r.created_at)}</td>
                <td style={TD_STYLE}>{r.admin_username ?? `#${r.admin_user_id}`}</td>
                <td style={TD_STYLE}><code style={{ fontSize: 12 }}>{r.action}</code></td>
                <td style={TD_STYLE}>{r.target_type ? `${r.target_type} #${r.target_id}` : '—'}</td>
                <td style={{ ...TD_STYLE, maxWidth: 380 }}>
                  {Object.keys(r.detail).length === 0 ? '—' : (
                    <details>
                      <summary style={{ cursor: 'pointer', fontSize: 12.5, color: 'var(--color-ink-500)' }}>
                        {Object.keys(r.detail).join(', ')}
                      </summary>
                      <pre style={{ margin: '6px 0 0', fontSize: 11.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: 'var(--color-ink-600)' }}>
                        {JSON.stringify(r.detail, null, 2)}
                      </pre>
                    </details>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination total={total} page={page} pageSize={pageSize} noun="actions" onPage={setPage} />
    </div>
  )
}
