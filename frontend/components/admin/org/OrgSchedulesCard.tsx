'use client'
import { useState } from 'react'
import { adminDeactivateSchedule } from '@/lib/api'
import type { AdminScheduleRow } from '@/lib/types'
import { ConfirmModal } from '@/components/ConfirmModal'
import type { ToastVariant } from '@/components/Toast'
import { TH_STYLE, TD_STYLE, zebra, fmtDate } from '../AdminTable'
import { apiErr } from '../UserModals'

const CARD: React.CSSProperties = {
  background: 'var(--color-surface)', borderRadius: 'var(--radius-card)',
  boxShadow: 'var(--shadow-card)', padding: 0, marginBottom: 18, overflowX: 'auto',
}

function options(s: AdminScheduleRow): string {
  const parts = [
    s.top_n ? `top ${s.top_n}` : null,
    s.radius_mi ? `${s.radius_mi} mi of ${s.center_address ?? '…'}` : null,
  ].filter(Boolean)
  return parts.length ? parts.join(' · ') : '—'
}

/** The org's pipeline schedules — what a plan downgrade or a lower territory
 *  limit silently deactivates. Deactivate only: re-enabling needs the
 *  territory guards the owner's Settings page runs. */
export function OrgSchedulesCard({ accountId, orgName, schedules, onChanged, onToast }: {
  accountId: number
  orgName: string
  schedules: AdminScheduleRow[]
  onChanged: () => Promise<void> | void
  onToast: (msg: string, variant?: ToastVariant) => void
}) {
  const [target, setTarget] = useState<AdminScheduleRow | null>(null)
  const [working, setWorking] = useState(false)

  async function deactivate(s: AdminScheduleRow) {
    setWorking(true)
    try {
      await adminDeactivateSchedule(accountId, s.id)
      onToast(`Schedule for ${s.zip} deactivated`)
      setTarget(null)
      await onChanged()
    } catch (e: unknown) {
      onToast(apiErr(e, 'Could not deactivate the schedule'), 'error')
    } finally {
      setWorking(false)
    }
  }

  return (
    <div style={CARD}>
      <h2 className="t-eyebrow" style={{ margin: 0, padding: '14px 16px 8px' }}>Pipeline schedules</h2>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={TH_STYLE}>ZIP</th>
            <th style={TH_STYLE}>Vertical</th>
            <th style={TH_STYLE}>When (UTC)</th>
            <th style={TH_STYLE}>Options</th>
            <th style={TH_STYLE}>Status</th>
            <th style={TH_STYLE}>Created</th>
            <th style={TH_STYLE}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {schedules.length === 0 && (
            <tr><td colSpan={7} style={{ ...TD_STYLE, textAlign: 'center', padding: '20px 0', color: 'var(--color-ink-400)' }}>No schedules</td></tr>
          )}
          {schedules.map((s, i) => (
            <tr key={s.id} style={{ background: zebra(i), opacity: s.is_active ? 1 : 0.6 }}>
              <td style={TD_STYLE} className="tabular">{s.zip}</td>
              <td style={TD_STYLE}>{s.vertical ?? '—'}</td>
              <td style={{ ...TD_STYLE, textTransform: 'capitalize' }}>{s.day_of_week} {s.hour}:00</td>
              <td style={TD_STYLE}>{options(s)}</td>
              <td style={TD_STYLE}>
                <span style={{ fontSize: 12, color: s.is_active ? 'var(--color-moss)' : 'var(--color-ink-400)' }}>
                  {s.is_active ? 'active' : 'inactive'}
                </span>
              </td>
              <td style={TD_STYLE}>{fmtDate(s.created_at)}</td>
              <td style={{ ...TD_STYLE, whiteSpace: 'nowrap' }}>
                {s.is_active && (
                  <button className="btn-secondary" style={{ fontSize: 12, padding: '3px 10px', color: 'var(--color-danger)' }} onClick={() => setTarget(s)}>
                    Deactivate
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p style={{ margin: 0, padding: '8px 16px 14px', fontSize: 12, color: 'var(--color-ink-400)', lineHeight: 1.5 }}>
        A plan downgrade or a lower territory limit deactivates the newest schedules beyond the
        limit. The owner can re-enable a schedule from Settings once their limit allows it.
      </p>
      {target && (
        <ConfirmModal
          title={`Deactivate the ${target.zip} schedule?`}
          message={`${orgName} stops receiving scheduled runs for ${target.zip}. The owner can turn it back on from Settings if their territory limit allows.`}
          confirmLabel="Deactivate"
          danger
          loading={working}
          onCancel={() => setTarget(null)}
          onConfirm={() => deactivate(target)}
        />
      )}
    </div>
  )
}
