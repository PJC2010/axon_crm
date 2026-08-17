'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import { KeyRound, Pencil, Plus, Search, ShieldCheck, Trash2 } from 'lucide-react'
import { adminAccounts, adminUsers } from '@/lib/api'
import type { AdminUserRow } from '@/lib/types'
import { ToastStack, useToast } from '@/components/Toast'
import { usePlatformAdmin } from '@/hooks/usePlatformAdmin'
import { TH_STYLE, TD_STYLE, zebra, fmtDate, fmtDateTime, Pagination } from './AdminTable'
import { CreateUserModal, DeleteUserModal, EditUserModal, ResetLinkModal, SetPasswordModal } from './UserModals'

export function AdminUsers() {
  const { me } = usePlatformAdmin()
  const { toasts, show, dismiss } = useToast()
  const [rows, setRows] = useState<AdminUserRow[]>([])
  const [total, setTotal] = useState(0)
  const [orgs, setOrgs] = useState<{ id: number; name: string }[]>([])

  const [q, setQ] = useState('')
  const [orgFilter, setOrgFilter] = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [activeFilter, setActiveFilter] = useState('')
  const [verifiedFilter, setVerifiedFilter] = useState('')
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const pageSize = 50

  const [creating, setCreating] = useState(false)
  const [editUser, setEditUser] = useState<AdminUserRow | null>(null)
  const [resetUser, setResetUser] = useState<AdminUserRow | null>(null)
  const [pwUser, setPwUser] = useState<AdminUserRow | null>(null)
  const [deleteUser, setDeleteUser] = useState<AdminUserRow | null>(null)

  useEffect(() => {
    adminAccounts({ page_size: 100, sort: 'name' })
      .then((p) => setOrgs(p.items.map((a) => ({ id: a.id, name: a.name }))))
      .catch(() => setOrgs([]))
  }, [])

  // Monotonic request id: a slow filtered query resolving after a newer one
  // must not overwrite the newer rows (the debounce only cancels un-fired timers).
  const reqRef = useRef(0)

  const load = useCallback(async () => {
    const reqId = ++reqRef.current
    setLoading(true)
    setError(null)
    try {
      const p = await adminUsers({
        q: q || undefined,
        account_id: orgFilter ? Number(orgFilter) : undefined,
        role: roleFilter || undefined,
        is_active: activeFilter === '' ? undefined : activeFilter === 'true',
        email_verified: verifiedFilter === '' ? undefined : verifiedFilter === 'true',
        page, page_size: pageSize,
      })
      if (reqId !== reqRef.current) return
      setRows(p.items)
      setTotal(p.total)
    } catch (e: unknown) {
      if (reqId !== reqRef.current) return
      setError(e instanceof Error ? e.message : 'Failed to load users')
    } finally {
      if (reqId === reqRef.current) setLoading(false)
    }
  }, [q, orgFilter, roleFilter, activeFilter, verifiedFilter, page])

  useEffect(() => {
    const t = setTimeout(load, q ? 300 : 0)
    return () => clearTimeout(t)
  }, [load, q])

  const resetPage = () => setPage(1)

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 14, flexWrap: 'wrap' }}>
        <div style={{ position: 'relative', flex: '1 1 200px', maxWidth: 300 }}>
          <Search size={13} strokeWidth={1.5} color="var(--color-ink-400)" style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)' }} />
          <input
            className="drawer-input"
            placeholder="Search by email or username…"
            value={q}
            onChange={(e) => { setQ(e.target.value); resetPage() }}
            style={{ width: '100%', paddingLeft: 30 }}
          />
        </div>
        <select className="select-field" value={orgFilter} onChange={(e) => { setOrgFilter(e.target.value); resetPage() }}>
          <option value="">Any org</option>
          {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
        <select className="select-field" value={roleFilter} onChange={(e) => { setRoleFilter(e.target.value); resetPage() }}>
          <option value="">Any role</option>
          <option value="owner">owner</option>
          <option value="sales_rep">sales_rep</option>
        </select>
        <select className="select-field" value={activeFilter} onChange={(e) => { setActiveFilter(e.target.value); resetPage() }}>
          <option value="">Any status</option>
          <option value="true">Active</option>
          <option value="false">Disabled</option>
        </select>
        <select className="select-field" value={verifiedFilter} onChange={(e) => { setVerifiedFilter(e.target.value); resetPage() }}>
          <option value="">Any verification</option>
          <option value="true">Verified</option>
          <option value="false">Unverified</option>
        </select>
        <button className="btn-primary" style={{ display: 'inline-flex', alignItems: 'center', gap: 5, marginLeft: 'auto' }} onClick={() => setCreating(true)}>
          <Plus size={13} strokeWidth={2} /> New user
        </button>
      </div>

      {error && <p style={{ color: 'var(--color-danger)', fontSize: 13 }}>{error}</p>}

      <div style={{ background: 'var(--color-surface)', borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)', overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={TH_STYLE}>User</th>
              <th style={TH_STYLE}>Org</th>
              <th style={TH_STYLE}>Role</th>
              <th style={TH_STYLE}>Status</th>
              <th style={TH_STYLE}>Last login</th>
              <th style={TH_STYLE}>Created</th>
              <th style={TH_STYLE}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && rows.length === 0 && (
              <tr><td colSpan={7} style={{ ...TD_STYLE, textAlign: 'center', padding: '48px 0', color: 'var(--color-ink-400)' }}>Loading…</td></tr>
            )}
            {!loading && rows.length === 0 && (
              <tr><td colSpan={7} style={{ ...TD_STYLE, textAlign: 'center', padding: '48px 0', color: 'var(--color-ink-400)' }}>No users match</td></tr>
            )}
            {rows.map((u, i) => (
              <tr key={u.id} style={{ background: zebra(i) }}>
                <td style={TD_STYLE}>
                  <span style={{ fontWeight: 600, color: 'var(--color-ink-900)' }}>{u.username}</span>
                  {u.is_platform_admin && (
                    <span title="Platform admin" style={{ marginLeft: 6, verticalAlign: 'middle', display: 'inline-flex' }}>
                      <ShieldCheck size={13} strokeWidth={1.75} color="var(--color-accent)" />
                    </span>
                  )}
                  <div style={{ fontSize: 12, color: 'var(--color-ink-400)' }}>{u.email}</div>
                </td>
                <td style={TD_STYLE}>{u.account_name} <span style={{ color: 'var(--color-ink-400)', fontSize: 12 }}>#{u.account_id}</span></td>
                <td style={TD_STYLE}>{u.role}</td>
                <td style={TD_STYLE}>
                  <span style={{ fontSize: 12, color: u.is_active ? 'var(--color-moss)' : 'var(--color-danger)' }}>
                    {u.is_active ? 'active' : 'disabled'}
                  </span>
                  {!u.email_verified && <span style={{ fontSize: 12, color: 'var(--color-warning)', marginLeft: 8 }}>unverified</span>}
                </td>
                <td style={TD_STYLE}>{fmtDateTime(u.last_login_at)}</td>
                <td style={TD_STYLE}>{fmtDate(u.created_at)}</td>
                <td style={{ ...TD_STYLE, whiteSpace: 'nowrap' }}>
                  <button className="dash-icon-btn borderless" title="Edit user" onClick={() => setEditUser(u)}><Pencil size={13} strokeWidth={1.5} /></button>
                  <button className="dash-icon-btn borderless" title="Password reset link" onClick={() => setResetUser(u)}><KeyRound size={13} strokeWidth={1.5} /></button>
                  <button className="dash-icon-btn borderless" title="Set temporary password" style={{ fontSize: 11.5 }} onClick={() => setPwUser(u)}>set pw</button>
                  {/* Deleting yourself is refused server-side; hiding the button
                      keeps the dead end out of the row entirely. */}
                  {u.id !== me?.id && (
                    <button
                      className="dash-icon-btn borderless"
                      title="Delete user"
                      style={{ color: 'var(--color-danger)' }}
                      onClick={() => setDeleteUser(u)}
                    >
                      <Trash2 size={13} strokeWidth={1.5} />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination total={total} page={page} pageSize={pageSize} noun="users" onPage={setPage} />

      {creating && <CreateUserModal onClose={() => setCreating(false)} onCreated={load} onToast={show} />}
      {editUser && <EditUserModal user={editUser} selfId={me?.id ?? null} onClose={() => setEditUser(null)} onSaved={load} onToast={show} />}
      {resetUser && <ResetLinkModal user={resetUser} onClose={() => setResetUser(null)} onToast={show} />}
      {pwUser && <SetPasswordModal user={pwUser} onClose={() => setPwUser(null)} onToast={show} />}
      {deleteUser && <DeleteUserModal user={deleteUser} onClose={() => setDeleteUser(null)} onDeleted={load} onToast={show} />}
      <ToastStack toasts={toasts} onDismiss={dismiss} />
    </div>
  )
}
