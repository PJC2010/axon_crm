'use client'
import { useState } from 'react'
import { adminSetLimits } from '@/lib/api'
import type { AdminUsageBlock } from '@/lib/types'
import { ConfirmModal } from '@/components/ConfirmModal'
import { Tag } from '@/components/ds'
import type { ToastVariant } from '@/components/Toast'
import { apiErr, LABEL } from '../UserModals'

const CARD: React.CSSProperties = {
  background: 'var(--color-surface)', borderRadius: 'var(--radius-card)',
  boxShadow: 'var(--shadow-card)', padding: 16, marginBottom: 18,
}

/** "18 / 25" with a bar; "18 / ∞" when unlimited. */
function Meter({ label, used, limit, note }: { label: string; used: number; limit: number | null; note: string }) {
  const pct = limit === null || limit === 0 ? 0 : Math.min(100, (used / limit) * 100)
  const over = limit !== null && used > limit
  return (
    <div>
      <span className="t-eyebrow" style={{ display: 'block', marginBottom: 6 }}>{label}</span>
      <p className="tabular" style={{ margin: '0 0 6px', fontSize: 20, fontWeight: 700, color: over ? 'var(--color-danger)' : 'var(--color-ink-900)' }}>
        {used.toLocaleString()} <span style={{ color: 'var(--color-ink-400)', fontWeight: 500 }}>/ {limit === null ? '∞' : limit.toLocaleString()}</span>
      </p>
      <div style={{ height: 4, borderRadius: 2, background: 'var(--color-ink-100)', overflow: 'hidden', marginBottom: 6 }}>
        <div style={{ width: `${pct}%`, height: '100%', background: over ? 'var(--color-danger)' : 'var(--color-accent)' }} />
      </div>
      <span style={{ fontSize: 11.5, color: 'var(--color-ink-400)' }}>{note}</span>
    </div>
  )
}

/** Used-vs-limit meters plus the two override inputs. A checked "plan
 *  default" sends null, which the endpoint reads as "back to the plan". */
export function OrgLimitsCard({ accountId, orgName, usage, onSaved, onToast }: {
  accountId: number
  orgName: string
  usage: AdminUsageBlock
  onSaved: () => Promise<void> | void
  onToast: (msg: string, variant?: ToastVariant) => void
}) {
  const t = usage.territories
  const [scoringDefault, setScoringDefault] = useState(usage.scoring.override === null)
  const [scoring, setScoring] = useState(usage.scoring.override?.toString() ?? '')
  const [territoryDefault, setTerritoryDefault] = useState((t?.override ?? null) === null)
  const [territory, setTerritory] = useState(t?.override?.toString() ?? '')
  const [confirm, setConfirm] = useState(false)
  const [working, setWorking] = useState(false)

  const isInt = (s: string) => /^\d+$/.test(s.trim())
  const valid = (scoringDefault || isInt(scoring)) && (territoryDefault || isInt(territory))
  const newTerritory = territoryDefault ? (t?.plan_default ?? null) : Number(territory)
  const trims = t !== null && newTerritory !== null && newTerritory < t.used

  const fmtDefault = (v: number | null | undefined) => (v === null || v === undefined ? 'unlimited' : v.toLocaleString())

  async function save() {
    setWorking(true)
    try {
      await adminSetLimits(accountId, {
        scoring_monthly_limit: scoringDefault ? null : Number(scoring),
        territory_limit: territoryDefault ? null : Number(territory),
      })
      onToast('Limits saved')
      setConfirm(false)
      await onSaved()
    } catch (e: unknown) {
      onToast(apiErr(e, 'Failed to save limits'), 'error')
    } finally {
      setWorking(false)
    }
  }

  return (
    <div style={CARD}>
      <h2 className="t-eyebrow" style={{ margin: '0 0 12px' }}>Limits &amp; usage</h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 18, marginBottom: 16 }}>
        <Meter
          label="Scored reveals · this month"
          used={usage.scoring.used}
          limit={usage.scoring.limit}
          note={`plan default ${fmtDefault(usage.scoring.plan_default)}${usage.scoring.override !== null ? ' · overridden' : ''}`}
        />
        {t === null ? (
          <div>
            <span className="t-eyebrow" style={{ display: 'block', marginBottom: 6 }}>Territories</span>
            <p style={{ margin: 0, fontSize: 13, color: 'var(--color-ink-400)' }}>Could not be measured right now.</p>
          </div>
        ) : (
          <div>
            <Meter
              label="Territories (distinct ZIPs)"
              used={t.used}
              limit={t.limit}
              note={`plan default ${fmtDefault(t.plan_default)}${t.override !== null ? ' · overridden' : ''}`}
            />
            {t.zips.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 8 }}>
                {t.zips.map((z) => <Tag key={z}>{z}</Tag>)}
              </div>
            )}
          </div>
        )}
      </div>

      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <div>
          <label style={LABEL}>Monthly reveal limit</label>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <input className="drawer-input" inputMode="numeric" value={scoring} disabled={scoringDefault}
              onChange={(e) => setScoring(e.target.value)} placeholder="e.g. 250" style={{ width: 110 }} />
            <label style={{ fontSize: 12.5, color: 'var(--color-ink-600)', display: 'flex', gap: 5, alignItems: 'center', cursor: 'pointer' }}>
              <input type="checkbox" checked={scoringDefault} onChange={(e) => setScoringDefault(e.target.checked)} /> plan default
            </label>
          </div>
        </div>
        <div>
          <label style={LABEL}>Territory limit</label>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <input className="drawer-input" inputMode="numeric" value={territory} disabled={territoryDefault}
              onChange={(e) => setTerritory(e.target.value)} placeholder="e.g. 5" style={{ width: 110 }} />
            <label style={{ fontSize: 12.5, color: 'var(--color-ink-600)', display: 'flex', gap: 5, alignItems: 'center', cursor: 'pointer' }}>
              <input type="checkbox" checked={territoryDefault} onChange={(e) => setTerritoryDefault(e.target.checked)} /> plan default
            </label>
          </div>
        </div>
        <button className="btn-primary" disabled={working || !valid} onClick={() => setConfirm(true)}>Save limits</button>
      </div>
      <p style={{ margin: '10px 0 0', fontSize: 12, color: 'var(--color-ink-400)', lineHeight: 1.5 }}>
        Overrides survive plan changes until cleared. Lowering the territory limit below the ZIPs in use
        deactivates the newest schedules beyond it, exactly as a plan downgrade does.
      </p>

      {confirm && (
        <ConfirmModal
          title="Save limit overrides?"
          message={
            `${orgName}: reveals ${scoringDefault ? 'plan default' : Number(scoring).toLocaleString()} / month, ` +
            `territories ${territoryDefault ? 'plan default' : Number(territory).toLocaleString()}.` +
            (trims ? ` This is below the ${t!.used} ZIPs in use — the newest schedules beyond the limit will be deactivated.` : '')
          }
          confirmLabel="Save limits"
          danger={trims}
          loading={working}
          onCancel={() => setConfirm(false)}
          onConfirm={save}
        />
      )}
    </div>
  )
}
