'use client'
import { Skeleton, SkeletonCards, Tag } from '@/components/ds'
import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { ArrowLeft, KeyRound, LogOut, Pencil, ShieldCheck, Trash2 } from 'lucide-react'
import {
  adminAccount, adminAccountActivity, adminDeleteAccount, adminRevokeSessions, adminSetPlan,
  adminSetTrial,
} from '@/lib/api'
import { clearToken } from '@/lib/auth'
import { clearEntitlementsCache } from '@/hooks/useEntitlements'
import type {
  AdminAccountDetail, AdminDeleteAccountResult, AdminMember, AdminOrgActivityRow,
} from '@/lib/types'
import { ConfirmModal } from '@/components/ConfirmModal'
import { ToastStack, useToast } from '@/components/Toast'
import { clearPlatformAdminCache, usePlatformAdmin } from '@/hooks/usePlatformAdmin'
import { TH_STYLE, TD_STYLE, zebra, fmtDate, fmtDateTime } from './AdminTable'
import {
  DangerButton, DeleteUserModal, EditUserModal, ERR, Modal, ResetLinkModal,
  SetPasswordModal, apiErr,
} from './UserModals'
import { OrgEditModal } from './org/OrgEditModal'
import { OrgLimitsCard } from './org/OrgLimitsCard'
import { OrgSchedulesCard } from './org/OrgSchedulesCard'
import { OrgUsageCard } from './org/OrgUsageCard'

const CARD: React.CSSProperties = {
  background: 'var(--color-surface)', borderRadius: 'var(--radius-card)',
  boxShadow: 'var(--shadow-card)', padding: 16, marginBottom: 18,
}

const PLANS = ['starter', 'growth', 'pro']

function fmtDuration(seconds: number): string {
  return seconds < 60 ? `${seconds}s` : `${Math.round(seconds / 60)}m`
}

/** Type-the-name confirmation for an irreversible org purge. The name match is
 *  re-checked server-side; requiring it here too is what stops a stray click on
 *  the wrong row from ever reaching the endpoint. */
function DeleteOrgModal({ detail, onClose, onDeleted }: {
  detail: AdminAccountDetail
  onClose: () => void
  onDeleted: () => void
}) {
  const [typed, setTyped] = useState('')
  const [working, setWorking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AdminDeleteAccountResult | null>(null)
  const matches = typed.trim() === detail.name

  // Only the non-zero counts, so this reads as "here is what you are about to
  // destroy" rather than a table of mostly zeroes.
  const nonZero = (counts: Record<string, number>) =>
    Object.entries(counts).filter(([, n]) => n > 0)

  async function remove() {
    setWorking(true)
    setError(null)
    try {
      setResult(await adminDeleteAccount(detail.id, typed.trim()))
    } catch (e: unknown) {
      setError(apiErr(e, 'Failed to delete organization'))
    } finally {
      setWorking(false)
    }
  }

  // The page behind this modal describes an org that no longer exists, so the
  // receipt is shown here rather than after navigating away from it.
  if (result) {
    return (
      <Modal title={`${result.name} deleted`} onClose={onDeleted} width={470}>
        <p style={{ margin: '0 0 12px', fontSize: 13, color: 'var(--color-ink-600)', lineHeight: 1.55 }}>
          The organization and everything it owned has been removed.
        </p>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 14px', fontSize: 12.5, color: 'var(--color-ink-700)', marginBottom: 4 }}>
          {nonZero(result.counts).map(([key, n]) => (
            <span key={key}><strong className="tabular">{n.toLocaleString()}</strong> {key.replace(/_/g, ' ')}</span>
          ))}
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}>
          <button className="btn-primary" onClick={onDeleted}>All orgs</button>
        </div>
      </Modal>
    )
  }

  return (
    <Modal title={`Delete ${detail.name}?`} onClose={onClose} width={470}>
      <p style={{ margin: '0 0 12px', fontSize: 13, color: 'var(--color-ink-600)', lineHeight: 1.55 }}>
        This permanently destroys the organization and everything inside it. There is no undo
        and no export — take one first if the data matters.
      </p>
      <div style={{
        background: 'var(--color-danger-bg)', borderRadius: 'var(--radius-card)',
        padding: '10px 12px', marginBottom: 14,
      }}>
        <span className="t-eyebrow" style={{ display: 'block', marginBottom: 6 }}>Will be deleted</span>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 14px', fontSize: 12.5, color: 'var(--color-ink-700)' }}>
          <span><strong className="tabular">{detail.members.length}</strong> user{detail.members.length === 1 ? '' : 's'}</span>
          {nonZero(detail.counts).map(([key, n]) => (
            <span key={key}><strong className="tabular">{n.toLocaleString()}</strong> {key.replace(/_/g, ' ')}</span>
          ))}
        </div>
      </div>
      <label style={{ fontSize: 12.5, color: 'var(--color-ink-600)', display: 'block', marginBottom: 6 }}>
        Type <strong style={{ color: 'var(--color-ink-900)' }}>{detail.name}</strong> to confirm:
      </label>
      <input
        className="drawer-input"
        value={typed}
        onChange={(e) => setTyped(e.target.value)}
        autoFocus
        style={{ width: '100%' }}
      />
      {error && <p style={ERR}>{error}</p>}
      {/* A purge is one transaction and Postgres does the work per row, so a
       *  big org takes tens of seconds. Say so while it runs — an operator who
       *  reads a still spinner as a hang closes the tab and rolls it back. */}
      {working && (detail.counts.leads ?? 0) > 25_000 && (
        <p style={{ margin: '10px 0 0', fontSize: 12.5, color: 'var(--color-ink-600)', lineHeight: 1.5 }}>
          {detail.counts.leads.toLocaleString()} leads — this can take a minute. Leave this
          tab open; closing it cancels the delete and the organization stays.
        </p>
      )}
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
        <button className="btn-secondary" onClick={onClose} disabled={working}>Cancel</button>
        <DangerButton onClick={remove} disabled={!matches || working}>
          {working ? 'Deleting…' : 'Delete organization'}
        </DangerButton>
      </div>
    </Modal>
  )
}

export function AdminOrgDetail({ accountId }: { accountId: number }) {
  const router = useRouter()
  const { me } = usePlatformAdmin()
  const { toasts, show, dismiss } = useToast()
  const [detail, setDetail] = useState<AdminAccountDetail | null>(null)
  const [activity, setActivity] = useState<AdminOrgActivityRow[]>([])
  const [error, setError] = useState<string | null>(null)

  const [plan, setPlan] = useState('pro')
  const [modules, setModules] = useState<Record<string, boolean>>({})
  const [trialDate, setTrialDate] = useState('')
  const [confirm, setConfirm] = useState<null | 'plan' | 'modules' | 'extend' | 'expire'>(null)
  const [working, setWorking] = useState(false)

  const [resetUser, setResetUser] = useState<AdminMember | null>(null)
  const [pwUser, setPwUser] = useState<AdminMember | null>(null)
  const [editUser, setEditUser] = useState<AdminMember | null>(null)
  const [deleteUser, setDeleteUser] = useState<AdminMember | null>(null)
  const [deletingOrg, setDeletingOrg] = useState(false)
  const [editing, setEditing] = useState(false)
  const [revokeUser, setRevokeUser] = useState<AdminMember | null>(null)
  const [activityDays, setActivityDays] = useState(30)

  const load = useCallback(async () => {
    setError(null)
    try {
      const d = await adminAccount(accountId)
      setDetail(d)
      setPlan(d.plan?.plan_name ?? 'pro')
      setModules(d.modules)
    } catch (e: unknown) {
      setError(apiErr(e, 'Failed to load org'))
    }
  }, [accountId])

  useEffect(() => { load() }, [load])

  // Activity is a nice-to-have — its failure degrades to an empty table
  // rather than discarding the org detail we already have. Its own effect so
  // changing the range refetches only this table.
  useEffect(() => {
    let alive = true
    adminAccountActivity(accountId, activityDays)
      .then((a) => { if (alive) setActivity(a.items) })
      .catch(() => { /* keep whatever activity we last had */ })
    return () => { alive = false }
  }, [accountId, activityDays])

  async function run(fn: () => Promise<unknown>, okMsg: string) {
    setWorking(true)
    try {
      await fn()
      show(okMsg)
      setConfirm(null)
      await load()
    } catch (e: unknown) {
      show(apiErr(e, 'Change failed'), 'error')
    } finally {
      setWorking(false)
    }
  }

  async function revoke(m: AdminMember) {
    setWorking(true)
    try {
      const r = await adminRevokeSessions(m.id)
      setRevokeUser(null)
      if (r.self) {
        // Our own token just died server-side; leave cleanly rather than let
        // the next request bounce us with a 401.
        clearToken()
        clearEntitlementsCache()
        clearPlatformAdminCache()
        router.push('/login')
        return
      }
      show(`${m.username} signed out everywhere`)
    } catch (e: unknown) {
      show(apiErr(e, 'Could not revoke sessions'), 'error')
    } finally {
      setWorking(false)
    }
  }

  if (error) return <p style={{ color: 'var(--color-danger)', fontSize: 13 }}>{error}</p>
  if (!detail) return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Skeleton h={24} w={220} />
      <SkeletonCards count={3} columns={3} h={84} gap={12} />
      <Skeleton h={220} radius="var(--radius-card)" />
    </div>
  )

  const billing = detail.billing
  const hasSubscription = billing?.has_subscription === true
  // The delete guards, mirrored from api/admin_logic.py::validate_account_delete
  // so the danger zone explains why it's unavailable instead of only 409-ing.
  const isOwnOrg = me?.account_id === detail.id
  const orgPlatformAdmins = detail.members.filter((m) => m.is_platform_admin).map((m) => m.username)
  // Full-override save: everything checked is enabled, everything unchecked
  // disabled — resolve_plan_modules applies these on top of the plan defaults.
  const checkedKeys = Object.keys(modules).filter((k) => modules[k])
  const uncheckedKeys = Object.keys(modules).filter((k) => !modules[k])
  // Module saves must send the org's STORED plan, not the dropdown state —
  // otherwise a stray dropdown change plus "Save modules" would silently
  // reassign the plan (and with it the scoring limit) as a side effect.
  const storedPlan = detail.plan?.plan_name ?? 'pro'

  return (
    <div>
      <Link href="/admin/orgs" style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12.5, color: 'var(--color-ink-500)', textDecoration: 'none', marginBottom: 12 }}>
        <ArrowLeft size={13} strokeWidth={1.5} /> All orgs
      </Link>

      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
        <h1 style={{ margin: 0, fontFamily: 'var(--font-display)', fontSize: 24, fontWeight: 600, color: 'var(--color-ink-900)' }}>{detail.name}</h1>
        <span style={{ fontSize: 13, color: 'var(--color-ink-400)' }}>#{detail.id} · {detail.business_type} · created {fmtDate(detail.created_at)}</span>
        <button
          className="btn-secondary"
          style={{ fontSize: 12.5, padding: '4px 10px', marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 5 }}
          onClick={() => setEditing(true)}
        >
          <Pencil size={12} strokeWidth={1.5} /> Edit
        </button>
      </div>

      {/* ── Usage counts ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', gap: 10, marginBottom: 18 }}>
        {Object.entries(detail.counts).map(([key, value]) => (
          <div key={key} style={{ background: 'var(--color-surface)', borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)', padding: '12px 14px' }}>
            <span className="t-eyebrow" style={{ display: 'block', marginBottom: 6 }}>{key.replace(/_/g, ' ')}</span>
            <span className="tabular" style={{ fontSize: 20, fontWeight: 700, color: 'var(--color-ink-900)' }}>{value.toLocaleString()}</span>
          </div>
        ))}
      </div>

      {/* ── Plan & modules ── */}
      <div style={CARD}>
        <h2 className="t-eyebrow" style={{ margin: '0 0 12px' }}>Plan &amp; modules</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
          <select className="select-field" value={plan} onChange={(e) => setPlan(e.target.value)}>
            {PLANS.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
          <button className="btn-secondary" disabled={working} onClick={() => setConfirm('plan')}>Apply plan</button>
          <span style={{ fontSize: 12, color: 'var(--color-ink-400)' }}>
            Applying a plan resets module overrides to its defaults.
          </span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 6, marginBottom: 12 }}>
          {Object.entries(modules).map(([key, on]) => (
            <label key={key} style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 13, color: 'var(--color-ink-800)', cursor: 'pointer' }}>
              <input type="checkbox" checked={on} onChange={(e) => setModules({ ...modules, [key]: e.target.checked })} />
              {key}
            </label>
          ))}
        </div>
        <button className="btn-primary" disabled={working} onClick={() => setConfirm('modules')}>Save modules</button>
      </div>

      {/* ── Limits & usage (overrides for the two account_plans columns that were raw-SQL only) ── */}
      <OrgLimitsCard
        key={`${detail.usage.scoring.override}-${detail.usage.territories?.override}`}
        accountId={accountId}
        orgName={detail.name}
        usage={detail.usage}
        onSaved={load}
        onToast={show}
      />

      {/* ── Billing & trial ── */}
      <div style={CARD}>
        <h2 className="t-eyebrow" style={{ margin: '0 0 12px' }}>Billing &amp; trial</h2>
        <p style={{ margin: '0 0 12px', fontSize: 13, color: 'var(--color-ink-600)' }}>
          Status: <strong style={{ color: 'var(--color-ink-900)' }}>{billing?.status ?? 'no billing row'}</strong>
          {billing?.trial_ends_at && <> · trial ends {fmtDate(billing.trial_ends_at)}</>}
          {billing?.current_period_end && <> · period ends {fmtDate(billing.current_period_end)}</>}
        </p>
        {hasSubscription ? (
          <p style={{ margin: 0, fontSize: 12.5, color: 'var(--color-ink-400)' }}>
            This org has a live Stripe subscription — manage it in Stripe, not here.
          </p>
        ) : (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <input className="drawer-input" type="date" value={trialDate} onChange={(e) => setTrialDate(e.target.value)} />
            <button className="btn-secondary" disabled={working || !trialDate} onClick={() => setConfirm('extend')}>Extend trial</button>
            <button
              className="btn-secondary"
              disabled={working || !billing}
              style={{ color: 'var(--color-danger)' }}
              onClick={() => setConfirm('expire')}
            >
              Expire trial now
            </button>
          </div>
        )}
      </div>

      {/* ── Members ── */}
      <div style={{ ...CARD, padding: 0, overflowX: 'auto' }}>
        <h2 className="t-eyebrow" style={{ margin: 0, padding: '14px 16px 8px' }}>Members</h2>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={TH_STYLE}>User</th>
              <th style={TH_STYLE}>Role</th>
              <th style={TH_STYLE}>Status</th>
              <th style={TH_STYLE}>Last login</th>
              <th style={TH_STYLE}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {detail.members.map((m, i) => (
              <tr key={m.id} style={{ background: zebra(i) }}>
                <td style={TD_STYLE}>
                  <span style={{ fontWeight: 600, color: 'var(--color-ink-900)' }}>{m.username}</span>
                  <span style={{ color: 'var(--color-ink-400)', marginLeft: 6, fontSize: 12 }}>{m.email}</span>
                  {(m.providers ?? []).map((p) => (
                    <Tag key={p} intent="info" style={{ marginLeft: 6 }} title={`Signs in with ${p}`}>{p}</Tag>
                  ))}
                </td>
                <td style={TD_STYLE}>{m.role}</td>
                <td style={TD_STYLE}>
                  <span style={{ fontSize: 12, color: m.is_active ? 'var(--color-moss)' : 'var(--color-danger)' }}>
                    {m.is_active ? 'active' : 'disabled'}
                  </span>
                  {!m.email_verified && <span style={{ fontSize: 12, color: 'var(--color-warning)', marginLeft: 8 }}>unverified</span>}
                  {m.is_platform_admin && (
                    <span title="Platform admin" style={{ marginLeft: 8, verticalAlign: 'middle', display: 'inline-flex' }}>
                      <ShieldCheck size={13} strokeWidth={1.75} color="var(--color-accent)" />
                    </span>
                  )}
                </td>
                <td style={TD_STYLE}>{fmtDateTime(m.last_login_at)}</td>
                <td style={{ ...TD_STYLE, whiteSpace: 'nowrap' }}>
                  <button className="dash-icon-btn borderless" title="Edit user" onClick={() => setEditUser(m)}><Pencil size={13} strokeWidth={1.5} /></button>
                  <button className="dash-icon-btn borderless" title="Password reset link" onClick={() => setResetUser(m)}><KeyRound size={13} strokeWidth={1.5} /></button>
                  <button className="dash-icon-btn borderless" title="Set temporary password" style={{ fontSize: 11.5 }} onClick={() => setPwUser(m)}>set pw</button>
                  <button className="dash-icon-btn borderless" title="Sign out everywhere" onClick={() => setRevokeUser(m)}><LogOut size={13} strokeWidth={1.5} /></button>
                  {m.id !== me?.id && (
                    <button
                      className="dash-icon-btn borderless"
                      title="Delete user"
                      style={{ color: 'var(--color-danger)' }}
                      onClick={() => setDeleteUser(m)}
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

      {/* ── Per-user activity (30d) ── */}
      <div style={{ ...CARD, padding: 0, overflowX: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px 8px' }}>
          <h2 className="t-eyebrow" style={{ margin: 0 }}>Activity · {activityDays} days</h2>
          <select className="select-field" value={activityDays} onChange={(e) => setActivityDays(Number(e.target.value))} style={{ fontSize: 12.5 }}>
            {[7, 30, 90].map((d) => <option key={d} value={d}>{d} days</option>)}
          </select>
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={TH_STYLE}>User</th>
              <th style={TH_STYLE}>Logins</th>
              <th style={TH_STYLE}>Lead events</th>
              <th style={TH_STYLE}>Calls</th>
              <th style={TH_STYLE}>Last login</th>
            </tr>
          </thead>
          <tbody>
            {activity.map((a, i) => (
              <tr key={a.user_id} style={{ background: zebra(i) }}>
                <td style={TD_STYLE}>{a.username}{!a.is_active && <span style={{ color: 'var(--color-danger)', fontSize: 11.5, marginLeft: 6 }}>disabled</span>}</td>
                <td style={TD_STYLE} className="tabular">{a.logins}</td>
                <td style={TD_STYLE} className="tabular">{a.lead_events}</td>
                <td style={TD_STYLE} className="tabular">{a.calls}</td>
                <td style={TD_STYLE}>{fmtDateTime(a.last_login_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ── Pipeline schedules ── */}
      <OrgSchedulesCard
        accountId={accountId}
        orgName={detail.name}
        schedules={detail.schedules}
        onChanged={load}
        onToast={show}
      />

      {/* ── Recent pipeline runs + events ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 18 }}>
        <div style={{ ...CARD, marginBottom: 0 }}>
          <h2 className="t-eyebrow" style={{ margin: '0 0 10px' }}>Recent pipeline runs</h2>
          {detail.recent_runs.length === 0 && <p style={{ margin: 0, fontSize: 12.5, color: 'var(--color-ink-400)' }}>None</p>}
          {detail.recent_runs.map((r) => (
            <div key={r.id} style={{ padding: '7px 0', borderBottom: '1px solid var(--color-ink-100)', fontSize: 12.5 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <span style={{ color: 'var(--color-ink-800)' }}>
                  {r.zip}{' '}
                  <span style={{ color: 'var(--color-ink-400)' }}>
                    ({r.triggered_by}{r.duration_seconds !== null ? ` · ${fmtDuration(r.duration_seconds)}` : ''})
                  </span>
                </span>
                <span style={{ color: r.status === 'done' ? 'var(--color-moss)' : r.status === 'running' ? 'var(--color-gold)' : 'var(--color-danger)' }}>{r.status}</span>
                <span style={{ color: 'var(--color-ink-400)' }}>{fmtDateTime(r.created_at)}</span>
              </div>
              {r.error && <div style={{ color: 'var(--color-danger)', fontSize: 11.5, marginTop: 2 }}>{r.error}</div>}
              {!r.error && r.properties_scored !== null && (
                <div style={{ color: 'var(--color-ink-400)', fontSize: 11.5, marginTop: 2 }}>{r.properties_scored.toLocaleString()} scored</div>
              )}
            </div>
          ))}
        </div>
        <div style={{ ...CARD, marginBottom: 0 }}>
          <h2 className="t-eyebrow" style={{ margin: '0 0 10px' }}>Recent lead events</h2>
          {detail.recent_events.length === 0 && <p style={{ margin: 0, fontSize: 12.5, color: 'var(--color-ink-400)' }}>None</p>}
          {detail.recent_events.map((ev) => (
            <div key={ev.id} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '7px 0', borderBottom: '1px solid var(--color-ink-100)', fontSize: 12.5 }}>
              <span style={{ color: 'var(--color-ink-800)' }}>{ev.event_type}{ev.channel ? ` · ${ev.channel}` : ''}</span>
              <span style={{ color: 'var(--color-ink-400)' }}>{ev.actor ?? '—'}</span>
              <span style={{ color: 'var(--color-ink-400)' }}>{fmtDateTime(ev.occurred_at)}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ── Usage (what this org costs the platform) ── */}
      <div style={{ marginTop: 18 }}>
        <OrgUsageCard accountId={accountId} />
      </div>

      {/* ── Danger zone ── */}
      <div style={{ ...CARD, marginBottom: 0, border: '1px solid var(--color-danger)' }}>
        <h2 className="t-eyebrow" style={{ margin: '0 0 10px', color: 'var(--color-danger)' }}>Danger zone</h2>
        <p style={{ margin: '0 0 12px', fontSize: 13, color: 'var(--color-ink-600)', lineHeight: 1.55 }}>
          Deleting this organization destroys its leads, invoices, quotes, calls, notes and
          logins permanently. The shared parcel cache and the admin audit trail are kept.
        </p>
        {isOwnOrg ? (
          <p style={{ margin: 0, fontSize: 12.5, color: 'var(--color-ink-400)' }}>
            This is your own organization — it cannot be deleted from here.
          </p>
        ) : hasSubscription ? (
          <p style={{ margin: 0, fontSize: 12.5, color: 'var(--color-ink-400)' }}>
            Cancel the live Stripe subscription before deleting this organization.
          </p>
        ) : orgPlatformAdmins.length > 0 ? (
          <p style={{ margin: 0, fontSize: 12.5, color: 'var(--color-ink-400)' }}>
            {orgPlatformAdmins.join(', ')} {orgPlatformAdmins.length === 1 ? 'has' : 'have'}{' '}
            platform-admin access — revoke it (Edit user) before deleting this organization.
          </p>
        ) : (
          <DangerButton onClick={() => setDeletingOrg(true)} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <Trash2 size={13} strokeWidth={1.75} /> Delete organization
          </DangerButton>
        )}
      </div>

      {/* ── Modals ── */}
      {confirm === 'plan' && (
        <ConfirmModal
          title={`Apply the ${plan} plan?`}
          message={`${detail.name} moves to '${plan}' and its module overrides reset to the plan's defaults.`}
          confirmLabel="Apply plan"
          loading={working}
          onCancel={() => setConfirm(null)}
          onConfirm={() => run(() => adminSetPlan(accountId, plan), `Plan set to ${plan}`)}
        />
      )}
      {confirm === 'modules' && (
        <ConfirmModal
          title="Save module overrides?"
          message={`${detail.name} keeps the '${storedPlan}' plan with exactly the checked modules enabled.`}
          confirmLabel="Save modules"
          loading={working}
          onCancel={() => setConfirm(null)}
          onConfirm={() => run(() => adminSetPlan(accountId, storedPlan, checkedKeys, uncheckedKeys), 'Modules saved')}
        />
      )}
      {confirm === 'extend' && (
        <ConfirmModal
          title="Extend trial?"
          message={`${detail.name}'s trial becomes active until ${trialDate}.`}
          confirmLabel="Extend trial"
          loading={working}
          onCancel={() => setConfirm(null)}
          onConfirm={() => run(
            () => adminSetTrial(accountId, 'extend', `${trialDate}T23:59:59Z`),
            'Trial extended',
          )}
        />
      )}
      {confirm === 'expire' && (
        <ConfirmModal
          title="Expire trial now?"
          message={`${detail.name} downgrades to the starter module set immediately (data is kept; core CRM stays on).`}
          confirmLabel="Expire trial"
          danger
          loading={working}
          onCancel={() => setConfirm(null)}
          onConfirm={() => run(() => adminSetTrial(accountId, 'expire'), 'Trial expired')}
        />
      )}
      {deletingOrg && (
        <DeleteOrgModal
          detail={detail}
          onClose={() => setDeletingOrg(false)}
          // replace(), not push(): this page's URL now 404s, so it must not be
          // left in history for the back button to land on.
          onDeleted={() => router.replace('/admin/orgs')}
        />
      )}
      {deleteUser && (
        <DeleteUserModal
          user={deleteUser}
          onClose={() => setDeleteUser(null)}
          onDeleted={load}
          onToast={show}
        />
      )}
      {resetUser && <ResetLinkModal user={resetUser} onClose={() => setResetUser(null)} onToast={show} />}
      {editing && (
        <OrgEditModal
          detail={detail}
          onClose={() => setEditing(false)}
          onSaved={() => { setEditing(false); show('Organization saved'); load() }}
        />
      )}
      {revokeUser && (
        <ConfirmModal
          title={`Sign ${revokeUser.username} out everywhere?`}
          message={revokeUser.id === me?.id
            ? 'This is you. Every session you hold — including this one — ends immediately and you will be sent to the login page.'
            : `Every session ${revokeUser.username} holds ends on its next request. Their password is unchanged; they simply sign in again.`}
          confirmLabel="Sign out everywhere"
          danger
          loading={working}
          onCancel={() => setRevokeUser(null)}
          onConfirm={() => revoke(revokeUser)}
        />
      )}
      {pwUser && <SetPasswordModal user={pwUser} onClose={() => setPwUser(null)} onToast={show} />}
      {editUser && (
        <EditUserModal
          user={editUser}
          selfId={me?.id ?? null}
          onClose={() => setEditUser(null)}
          onSaved={load}
          onToast={show}
        />
      )}
      <ToastStack toasts={toasts} onDismiss={dismiss} />
    </div>
  )
}
