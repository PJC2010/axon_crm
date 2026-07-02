'use client'
import { useCallback, useEffect, useState } from 'react'
import { Plus, ShieldCheck, Trash2 } from 'lucide-react'
import type { Policy, PolicyPage, PolicyStatus } from '@/lib/types'
import { createPolicy, deletePolicy, getPolicies, updatePolicy } from '@/lib/api'
import { useEntitlements } from '@/hooks/useEntitlements'
import { fmtCurrency } from './format'

const SECTION_BORDER: React.CSSProperties = { borderBottom: '1px solid var(--color-ink-100)' }
const STATUSES: PolicyStatus[] = ['quoted', 'active', 'lapsed', 'cancelled']
const STATUS_COLOR: Record<PolicyStatus, string> = {
  quoted: 'var(--color-gold)',
  active: 'var(--color-moss)',
  lapsed: 'var(--color-danger)',
  cancelled: 'var(--color-ink-300)',
}

/**
 * Policies attached to a record (insurance book of business). Self-fetching by
 * leadId (ActivityPanel pattern); renders nothing when the `policies` module is
 * off, so non-insurance accounts are unaffected.
 */
export function PoliciesSection({ leadId }: { leadId: number }) {
  const { hasModule, loading: entLoading } = useEntitlements()
  const [page, setPage] = useState<PolicyPage | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [carrier, setCarrier] = useState('')
  const [policyType, setPolicyType] = useState('')
  const [premium, setPremium] = useState('')
  const [expiration, setExpiration] = useState('')
  const [saving, setSaving] = useState(false)

  const load = useCallback(() => {
    getPolicies({ property_id: leadId, page_size: 50 }).then(setPage).catch(() => setPage(null))
  }, [leadId])

  const enabled = hasModule('policies')
  useEffect(() => { if (enabled) load() }, [enabled, load])

  if (entLoading || !enabled) return null

  const items = page?.items ?? []

  async function handleAdd() {
    if (!carrier.trim() && !policyType.trim()) return
    setSaving(true)
    try {
      await createPolicy({
        property_id: leadId,
        carrier: carrier.trim() || undefined,
        policy_type: policyType.trim() || undefined,
        premium: premium ? Number(premium) : undefined,
        expiration_date: expiration || undefined,
      })
      setCarrier(''); setPolicyType(''); setPremium(''); setExpiration('')
      setShowForm(false)
      load()
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Failed to add policy')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section style={{ padding: '16px 24px', ...SECTION_BORDER }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <ShieldCheck size={13} strokeWidth={1.5} style={{ color: 'var(--color-accent)' }} />
          <p className="t-eyebrow" style={{ margin: 0 }}>Policies</p>
        </div>
        <button onClick={() => setShowForm(s => !s)} className="dash-icon-btn" style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
          <Plus size={12} strokeWidth={1.5} /> Add
        </button>
      </div>

      {page && page.active_count > 0 && (
        <p style={{ margin: '0 0 10px', fontSize: 12, color: 'var(--color-ink-500)' }}>
          <strong className="tabular" style={{ color: 'var(--color-ink-800)' }}>{fmtCurrency(page.premium_in_force)}</strong> premium in force
          · {page.active_count} active
          {page.next_expiration && <> · next renewal {page.next_expiration}</>}
        </p>
      )}

      {showForm && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
          <input value={carrier} onChange={e => setCarrier(e.target.value)} placeholder="Carrier" className="drawer-input" style={{ flex: 1, minWidth: 100 }} />
          <input value={policyType} onChange={e => setPolicyType(e.target.value)} placeholder="Line (auto, home…)" className="drawer-input" style={{ flex: 1, minWidth: 110 }} />
          <input value={premium} onChange={e => setPremium(e.target.value)} placeholder="Premium" type="number" className="drawer-input" style={{ width: 90 }} />
          <input value={expiration} onChange={e => setExpiration(e.target.value)} type="date" title="Expiration / renewal date" className="drawer-input" style={{ width: 140 }} />
          <button onClick={handleAdd} disabled={saving} className="dash-icon-btn" style={{ fontSize: 12, color: 'var(--color-accent)' }}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      )}

      {items.length === 0 ? (
        !showForm && <p style={{ margin: 0, fontSize: 12, color: 'var(--color-ink-400)' }}>No policies yet.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {items.map((p: Policy) => (
            <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
              <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {[p.carrier, p.policy_type].filter(Boolean).join(' · ') || p.policy_number || `Policy #${p.id}`}
              </span>
              {p.premium != null && <span className="tabular" style={{ color: 'var(--color-ink-500)', fontSize: 12 }}>{fmtCurrency(p.premium)}</span>}
              {p.expiration_date && <span style={{ color: 'var(--color-ink-400)', fontSize: 12 }}>exp {p.expiration_date}</span>}
              <select
                value={p.status}
                onChange={async e => { await updatePolicy(p.id, { status: e.target.value as PolicyStatus }); load() }}
                className="drawer-input"
                style={{ fontSize: 11, width: 96, color: STATUS_COLOR[p.status] }}
              >
                {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
              <button
                onClick={async () => { if (confirm('Delete this policy?')) { await deletePolicy(p.id); load() } }}
                className="dash-icon-btn" style={{ padding: 4 }} title="Delete"
              >
                <Trash2 size={11} strokeWidth={1.5} />
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
