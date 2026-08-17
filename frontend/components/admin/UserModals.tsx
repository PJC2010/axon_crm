'use client'
import { useEffect, useState } from 'react'
import { Copy, X } from 'lucide-react'
import {
  adminCreateUser, adminResetPassword, adminSetPassword, adminUpdateUser,
  adminAccounts, getBusinessTypes,
} from '@/lib/api'
import type {
  AdminMember, AdminResetLinkResult, AdminUserCreate, AdminUserUpdate,
  BusinessTypeInfo,
} from '@/lib/types'

/** Pull the .detail out of an `API 4xx: {"detail":"…"}` error message. */
export function apiErr(err: unknown, fallback: string): string {
  const msg = err instanceof Error ? err.message : ''
  const m = msg.match(/\{.*\}/)
  if (m) {
    try {
      const parsed = JSON.parse(m[0])
      if (typeof parsed.detail === 'string') return parsed.detail
    } catch { /* fall through */ }
  }
  return msg || fallback
}

function Modal({ title, onClose, children, width = 400 }: {
  title: string
  onClose: () => void
  children: React.ReactNode
  width?: number
}) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <>
      <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 200, background: 'rgba(22,24,29,0.4)', backdropFilter: 'blur(2px)' }} />
      <div role="dialog" aria-modal="true" style={{
        position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', zIndex: 201,
        width, maxWidth: 'calc(100vw - 32px)', maxHeight: 'calc(100vh - 48px)', overflowY: 'auto',
        background: 'var(--color-surface)', borderRadius: 'var(--radius-modal)',
        boxShadow: 'var(--shadow-modal)', padding: 20,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
          <p style={{ margin: 0, fontSize: 15, fontWeight: 600, color: 'var(--color-ink-900)' }}>{title}</p>
          <button onClick={onClose} aria-label="Close" style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4, color: 'var(--color-ink-400)', display: 'flex' }}>
            <X size={15} />
          </button>
        </div>
        {children}
      </div>
    </>
  )
}

const LABEL: React.CSSProperties = { fontSize: 11, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--color-ink-500)', marginBottom: 4, display: 'block' }
const ERR: React.CSSProperties = { margin: '10px 0 0', fontSize: 12.5, color: 'var(--color-danger)' }

/* ── Reset-password link ─────────────────────────────────────────────────────── */

export function ResetLinkModal({ user, onClose, onToast }: {
  user: Pick<AdminMember, 'id' | 'username' | 'email'>
  onClose: () => void
  onToast: (msg: string, variant?: 'success' | 'error') => void
}) {
  const [result, setResult] = useState<AdminResetLinkResult | null>(null)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function generate(sendEmail: boolean) {
    setWorking(true)
    setError(null)
    try {
      const r = await adminResetPassword(user.id, sendEmail)
      setResult(r)
      if (sendEmail) onToast(r.emailed ? `Reset link emailed to ${user.email}` : 'Link created — email is not configured, copy it instead', r.emailed ? 'success' : 'error')
    } catch (e: unknown) {
      setError(apiErr(e, 'Failed to create reset link'))
    } finally {
      setWorking(false)
    }
  }

  // Mint a copyable link immediately; "email a fresh link" mints again.
  useEffect(() => { generate(false) }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Modal title={`Reset password — ${user.username}`} onClose={onClose} width={460}>
      <p style={{ margin: '0 0 12px', fontSize: 13, color: 'var(--color-ink-500)', lineHeight: 1.5 }}>
        Send this one-time link to the user. It expires in {result?.expires_in_hours ?? 2} hours;
        generating a new link invalidates previous ones.
      </p>
      {result && (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 12 }}>
          <input className="drawer-input" readOnly value={result.reset_url} style={{ flex: 1, fontSize: 12 }} onFocus={(e) => e.currentTarget.select()} />
          <button
            className="btn-secondary"
            style={{ display: 'inline-flex', alignItems: 'center', gap: 5, whiteSpace: 'nowrap' }}
            onClick={async () => {
              await navigator.clipboard.writeText(result.reset_url)
              onToast('Reset link copied')
            }}
          >
            <Copy size={13} strokeWidth={1.5} /> Copy
          </button>
        </div>
      )}
      {error && <p style={ERR}>{error}</p>}
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 8 }}>
        <button className="btn-secondary" onClick={onClose}>Done</button>
        <button className="btn-primary" disabled={working} onClick={() => generate(true)}>
          {working ? 'Working…' : 'Email a fresh link'}
        </button>
      </div>
    </Modal>
  )
}

/* ── Direct temporary password ───────────────────────────────────────────────── */

export function SetPasswordModal({ user, onClose, onToast }: {
  user: Pick<AdminMember, 'id' | 'username'>
  onClose: () => void
  onToast: (msg: string, variant?: 'success' | 'error') => void
}) {
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save(e: React.FormEvent) {
    e.preventDefault()
    if (password.length < 8) { setError('Password must be at least 8 characters.'); return }
    if (password !== confirm) { setError('Passwords do not match.'); return }
    setSaving(true)
    setError(null)
    try {
      await adminSetPassword(user.id, password)
      onToast(`Password set for ${user.username}`)
      onClose()
    } catch (err: unknown) {
      setError(apiErr(err, 'Failed to set password'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title={`Set temporary password — ${user.username}`} onClose={onClose}>
      <form onSubmit={save} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div>
          <label style={LABEL}>New password</label>
          <input className="drawer-input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus style={{ width: '100%' }} />
        </div>
        <div>
          <label style={LABEL}>Confirm password</label>
          <input className="drawer-input" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} style={{ width: '100%' }} />
        </div>
        <p style={{ margin: 0, fontSize: 12, color: 'var(--color-ink-400)', lineHeight: 1.5 }}>
          Any outstanding reset links are invalidated. Share the password over a secure channel.
        </p>
        {error && <p style={ERR}>{error}</p>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
          <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Set password'}</button>
        </div>
      </form>
    </Modal>
  )
}

/* ── Edit user (role / flags) ────────────────────────────────────────────────── */

export function EditUserModal({ user, selfId, onClose, onSaved, onToast }: {
  user: AdminMember
  selfId: number | null
  onClose: () => void
  onSaved: () => void
  onToast: (msg: string, variant?: 'success' | 'error') => void
}) {
  const isSelf = selfId === user.id
  const [role, setRole] = useState(user.role)
  const [isActive, setIsActive] = useState(user.is_active)
  const [emailVerified, setEmailVerified] = useState(user.email_verified)
  const [platformAdmin, setPlatformAdmin] = useState(user.is_platform_admin)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save(e: React.FormEvent) {
    e.preventDefault()
    const body: AdminUserUpdate = {}
    if (role !== user.role) body.role = role
    if (isActive !== user.is_active) body.is_active = isActive
    if (emailVerified !== user.email_verified) body.email_verified = emailVerified
    if (platformAdmin !== user.is_platform_admin) body.is_platform_admin = platformAdmin
    if (Object.keys(body).length === 0) { onClose(); return }
    setSaving(true)
    setError(null)
    try {
      await adminUpdateUser(user.id, body)
      onToast(`Updated ${user.username}`)
      onSaved()
      onClose()
    } catch (err: unknown) {
      setError(apiErr(err, 'Failed to update user'))
    } finally {
      setSaving(false)
    }
  }

  const check = (checked: boolean, set: (v: boolean) => void, label: string, disabled = false, hint?: string) => (
    <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: disabled ? 'var(--color-ink-400)' : 'var(--color-ink-800)', cursor: disabled ? 'not-allowed' : 'pointer' }}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => set(e.target.checked)} />
      {label}
      {hint && <span style={{ fontSize: 11.5, color: 'var(--color-ink-400)' }}>{hint}</span>}
    </label>
  )

  return (
    <Modal title={`Edit user — ${user.username}`} onClose={onClose}>
      <form onSubmit={save} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div>
          <label style={LABEL}>Role (within their org)</label>
          <select className="select-field" value={role} onChange={(e) => setRole(e.target.value)} style={{ width: '100%' }}>
            <option value="owner">owner</option>
            <option value="sales_rep">sales_rep</option>
          </select>
        </div>
        {check(isActive, setIsActive, 'Active', isSelf && isActive, isSelf ? '(you cannot deactivate yourself)' : undefined)}
        {check(emailVerified, setEmailVerified, 'Email verified')}
        {check(platformAdmin, setPlatformAdmin, 'Platform admin', isSelf && platformAdmin, isSelf ? '(you cannot revoke your own access)' : '(full cross-org access)')}
        {error && <p style={ERR}>{error}</p>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
          <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
        </div>
      </form>
    </Modal>
  )
}

/* ── Create user (existing org or fresh org) ─────────────────────────────────── */

export function CreateUserModal({ defaultAccountId, onClose, onCreated, onToast }: {
  defaultAccountId?: number
  onClose: () => void
  onCreated: () => void
  onToast: (msg: string, variant?: 'success' | 'error') => void
}) {
  const [mode, setMode] = useState<'existing' | 'new'>(defaultAccountId ? 'existing' : 'new')
  const [orgs, setOrgs] = useState<{ id: number; name: string }[]>([])
  const [businessTypes, setBusinessTypes] = useState<BusinessTypeInfo[]>([])
  const [accountId, setAccountId] = useState<number | undefined>(defaultAccountId)
  const [orgName, setOrgName] = useState('')
  const [businessType, setBusinessType] = useState('home_services')
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('owner')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    adminAccounts({ page_size: 100, sort: 'name' })
      .then((p) => {
        setOrgs(p.items.map((a) => ({ id: a.id, name: a.name })))
        setAccountId((cur) => cur ?? p.items[0]?.id)
      })
      .catch(() => setOrgs([]))
    getBusinessTypes().then(setBusinessTypes).catch(() => setBusinessTypes([]))
  }, [])

  async function save(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    const body: AdminUserCreate = { email: email.trim(), password, role }
    if (username.trim()) body.username = username.trim()
    if (mode === 'existing') {
      if (!accountId) { setError('Choose an organization.'); return }
      body.account_id = accountId
    } else {
      if (!orgName.trim()) { setError('Organization name is required.'); return }
      body.new_account = { name: orgName.trim(), business_type: businessType }
    }
    setSaving(true)
    try {
      const created = await adminCreateUser(body)
      onToast(`Created ${created.username}`)
      onCreated()
      onClose()
    } catch (err: unknown) {
      setError(apiErr(err, 'Failed to create user'))
    } finally {
      setSaving(false)
    }
  }

  const radio = (value: 'existing' | 'new', label: string) => (
    <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: 'var(--color-ink-800)', cursor: 'pointer' }}>
      <input type="radio" name="org-mode" checked={mode === value} onChange={() => setMode(value)} />
      {label}
    </label>
  )

  return (
    <Modal title="New user" onClose={onClose} width={440}>
      <form onSubmit={save} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ display: 'flex', gap: 16 }}>
          {radio('existing', 'Existing org')}
          {radio('new', 'New org')}
        </div>
        {mode === 'existing' ? (
          <div>
            <label style={LABEL}>Organization</label>
            <select className="select-field" value={accountId ?? ''} onChange={(e) => setAccountId(Number(e.target.value))} style={{ width: '100%' }}>
              {orgs.map((o) => <option key={o.id} value={o.id}>{o.name} (#{o.id})</option>)}
            </select>
          </div>
        ) : (
          <>
            <div>
              <label style={LABEL}>Organization name</label>
              <input className="drawer-input" value={orgName} onChange={(e) => setOrgName(e.target.value)} style={{ width: '100%' }} />
            </div>
            <div>
              <label style={LABEL}>Business type</label>
              <select className="select-field" value={businessType} onChange={(e) => setBusinessType(e.target.value)} style={{ width: '100%' }}>
                {businessTypes.length === 0 && <option value="home_services">home_services</option>}
                {businessTypes.map((b) => <option key={b.key} value={b.key}>{b.label}</option>)}
              </select>
            </div>
          </>
        )}
        <div>
          <label style={LABEL}>Email</label>
          <input className="drawer-input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} style={{ width: '100%' }} />
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <div style={{ flex: 1 }}>
            <label style={LABEL}>Username (optional)</label>
            <input className="drawer-input" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="derived from email" style={{ width: '100%' }} />
          </div>
          <div style={{ width: 130 }}>
            <label style={LABEL}>Role</label>
            <select className="select-field" value={role} onChange={(e) => setRole(e.target.value)} disabled={mode === 'new'} style={{ width: '100%' }}>
              <option value="owner">owner</option>
              <option value="sales_rep">sales_rep</option>
            </select>
          </div>
        </div>
        <div>
          <label style={LABEL}>Password</label>
          <input className="drawer-input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="min 8 characters" style={{ width: '100%' }} />
        </div>
        {mode === 'new' && (
          <p style={{ margin: 0, fontSize: 12, color: 'var(--color-ink-400)', lineHeight: 1.5 }}>
            Provisions a full org (stages, plan, 14-day pro trial, workflows) with this user as its owner.
          </p>
        )}
        {error && <p style={ERR}>{error}</p>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
          <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={saving}>{saving ? 'Creating…' : 'Create user'}</button>
        </div>
      </form>
    </Modal>
  )
}
