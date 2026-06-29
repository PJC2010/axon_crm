'use client'
import { useEffect, useState } from 'react'
import { Check } from 'lucide-react'
import type { Lead, RecordFieldDef } from '@/lib/types'
import { getRecordFields, updateLeadCustomFields } from '@/lib/api'

const SECTION_BORDER: React.CSSProperties = { borderBottom: '1px solid var(--color-ink-100)' }

const INPUT_STYLE: React.CSSProperties = {
  flex: 1,
  fontSize: 13,
  padding: '6px 10px',
  borderRadius: 'var(--radius-input)',
  border: '1px solid var(--color-ink-200)',
  background: 'var(--color-paper)',
  color: 'var(--color-ink-900)',
  fontFamily: 'var(--font-sans)',
  outline: 'none',
}

/**
 * Account-defined custom fields for a record (the generic record-model layer).
 * Renders nothing when the account has defined no fields, so home-services
 * accounts are unaffected. Values persist to properties.custom_fields.
 */
export function CustomFieldsSection({
  lead,
  onSaved,
  onToast,
}: {
  lead: Lead
  onSaved?: (lead: Lead) => void
  onToast?: (message: string, variant?: 'success' | 'error') => void
}) {
  const [defs, setDefs] = useState<RecordFieldDef[]>([])
  // `draft` holds only the user's unsaved edits; displayed values fall back to the
  // record's stored value. This avoids seeding state in an effect (and resets
  // cleanly because the parent remounts this per lead via key={lead.id}).
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    getRecordFields().then(setDefs).catch(() => setDefs([]))
  }, [])

  if (defs.length === 0) return null

  const cf = (lead.custom_fields ?? {}) as Record<string, unknown>
  const orig = (key: string) => (cf[key] === null || cf[key] === undefined ? '' : String(cf[key]))
  const valueOf = (key: string) => (key in draft ? draft[key] : orig(key))
  const dirty = defs.some((d) => d.key in draft && draft[d.key] !== orig(d.key))

  function set(key: string, value: string) {
    setDraft((d) => ({ ...d, [key]: value }))
  }

  async function handleSave() {
    setSaving(true)
    // Only send edited fields; empty strings clear the key (null).
    const values: Record<string, unknown> = {}
    for (const d of defs) {
      if (!(d.key in draft)) continue
      const raw = draft[d.key]
      if (raw === '') { values[d.key] = null; continue }
      if (d.field_type === 'number') values[d.key] = Number(raw)
      else if (d.field_type === 'boolean') values[d.key] = raw === 'true'
      else values[d.key] = raw
    }
    try {
      const res = await updateLeadCustomFields(lead.id, values)
      setDraft({})
      onSaved?.({ ...lead, custom_fields: res.custom_fields })
      onToast?.('Saved')
    } catch {
      onToast?.('Save failed — please try again', 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section style={{ padding: '16px 24px', ...SECTION_BORDER }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <p className="t-eyebrow" style={{ margin: 0 }}>Details</p>
        {dirty && (
          <button
            onClick={handleSave}
            disabled={saving}
            className="dash-icon-btn"
            style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, color: 'var(--color-accent)' }}
          >
            <Check size={13} strokeWidth={2} /> {saving ? 'Saving…' : 'Save'}
          </button>
        )}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {defs.map((d) => (
          <label key={d.id} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ width: 110, fontSize: 12, color: 'var(--color-ink-500)', flexShrink: 0 }}>{d.label}</span>
            {d.field_type === 'select' ? (
              <select value={valueOf(d.key)} onChange={(e) => set(d.key, e.target.value)} style={INPUT_STYLE}>
                <option value="">—</option>
                {d.options.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            ) : d.field_type === 'boolean' ? (
              <select value={valueOf(d.key)} onChange={(e) => set(d.key, e.target.value)} style={INPUT_STYLE}>
                <option value="">—</option>
                <option value="true">Yes</option>
                <option value="false">No</option>
              </select>
            ) : (
              <input
                type={d.field_type === 'number' ? 'number' : d.field_type === 'date' ? 'date' : 'text'}
                value={valueOf(d.key)}
                onChange={(e) => set(d.key, e.target.value)}
                style={INPUT_STYLE}
              />
            )}
          </label>
        ))}
      </div>
    </section>
  )
}
