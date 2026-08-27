'use client'
import { useCallback, useEffect, useState } from 'react'
import { Plus, Send, ShieldCheck, Trash2 } from 'lucide-react'
import type { MessageTemplate, Policy, PolicyPage, PolicyStatus } from '@/lib/types'
import { createPolicy, deletePolicy, getMessageTemplates, getPolicies, sendLeadMessage, updatePolicy } from '@/lib/api'
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
  // Per-policy renewal reminder: which policy's composer is open + its state.
  const [templates, setTemplates] = useState<MessageTemplate[]>([])
  const [reminderFor, setReminderFor] = useState<number | null>(null)
  const [reminderTemplateId, setReminderTemplateId] = useState<number | ''>('')
  const [sendingReminder, setSendingReminder] = useState(false)
  const [reminderResult, setReminderResult] = useState<string | null>(null)

  const load = useCallback(() => {
    getPolicies({ property_id: leadId, page_size: 50 }).then(setPage).catch(() => setPage(null))
  }, [leadId])

  const enabled = hasModule('policies')
  useEffect(() => { if (enabled) load() }, [enabled, load])
  useEffect(() => {
    if (enabled) getMessageTemplates().then(setTemplates).catch(() => setTemplates([]))
  }, [enabled])

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
          <button onClick={handleAdd} disabled={saving} className="dash-icon-btn" style={{ fontSize: 12, color: 'var(--color-accent-300)' }}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      )}

      {items.length === 0 ? (
        !showForm && <p style={{ margin: 0, fontSize: 12, color: 'var(--color-ink-400)' }}>No policies yet.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {items.map((p: Policy) => (
            <div key={p.id}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
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
                {templates.length > 0 && (
                  <button
                    onClick={() => {
                      setReminderFor(r => (r === p.id ? null : p.id))
                      setReminderResult(null)
                    }}
                    className="dash-icon-btn" style={{ padding: 4 }} title="Send reminder about this policy"
                  >
                    <Send size={11} strokeWidth={1.5} />
                  </button>
                )}
                <button
                  onClick={async () => { if (confirm('Delete this policy?')) { await deletePolicy(p.id); load() } }}
                  className="dash-icon-btn" style={{ padding: 4 }} title="Delete"
                >
                  <Trash2 size={11} strokeWidth={1.5} />
                </button>
              </div>
              {reminderFor === p.id && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6, paddingLeft: 8 }}>
                  <select
                    value={reminderTemplateId}
                    onChange={e => { setReminderTemplateId(e.target.value ? Number(e.target.value) : ''); setReminderResult(null) }}
                    className="drawer-input" style={{ flex: 1, minWidth: 140, fontSize: 12 }}
                  >
                    <option value="">Choose a template…</option>
                    {templates.map(tpl => <option key={tpl.id} value={tpl.id}>{tpl.name} ({tpl.channel})</option>)}
                  </select>
                  <button
                    onClick={async () => {
                      if (reminderTemplateId === '') return
                      setSendingReminder(true)
                      setReminderResult(null)
                      try {
                        const res = await sendLeadMessage(leadId, { template_id: reminderTemplateId as number, policy_id: p.id })
                        setReminderResult(`Sent ${res.channel} to ${res.to}`)
                      } catch (err: unknown) {
                        setReminderResult(err instanceof Error ? err.message : 'Send failed')
                      } finally {
                        setSendingReminder(false)
                      }
                    }}
                    disabled={reminderTemplateId === '' || sendingReminder}
                    className="dash-icon-btn"
                    style={{ fontSize: 12, color: 'var(--color-accent-300)', opacity: reminderTemplateId === '' || sendingReminder ? 0.5 : 1 }}
                  >
                    {sendingReminder ? 'Sending…' : 'Send'}
                  </button>
                  {reminderResult && <span style={{ fontSize: 11, color: 'var(--color-ink-500)' }}>{reminderResult}</span>}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
