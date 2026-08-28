'use client'
import { useEffect, useState, FormEvent } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { getRecordFields, createRecordField, deleteRecordField } from '@/lib/api'
import { useTerminology } from '@/hooks/useTerminology'
import { useConfirm } from '@/hooks/useConfirm'
import type { RecordFieldDef, RecordFieldType } from '@/lib/types'

const TYPES: RecordFieldType[] = ['text', 'number', 'date', 'boolean', 'select']

/**
 * Owner-facing management of account custom fields (the generic record model).
 * Fields defined here appear on every record's drawer for data entry.
 */
export function CustomFieldsSettings() {
  const { t } = useTerminology()
  const { confirm, confirmDialog } = useConfirm()
  const [fields, setFields] = useState<RecordFieldDef[]>([])
  const [label, setLabel] = useState('')
  const [fieldType, setFieldType] = useState<RecordFieldType>('text')
  const [options, setOptions] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    getRecordFields().then(setFields).catch(() => setFields([]))
  }, [])

  async function handleAdd(e: FormEvent) {
    e.preventDefault()
    if (!label.trim()) return
    setSaving(true)
    try {
      const created = await createRecordField({
        label: label.trim(),
        field_type: fieldType,
        options: fieldType === 'select'
          ? options.split(',').map(o => o.trim()).filter(Boolean)
          : [],
      })
      setFields(prev => [...prev, created])
      setLabel(''); setOptions(''); setFieldType('text')
    } catch { /* surfaced by the disabled state resetting */ }
    finally { setSaving(false) }
  }

  async function handleDelete(id: number) {
    const ok = await confirm({
      title: 'Delete this field?',
      message: 'Existing values are kept in the database but no longer shown on any record.',
      confirmLabel: 'Delete field',
      danger: true,
    })
    if (!ok) return
    await deleteRecordField(id)
    setFields(prev => prev.filter(f => f.id !== id))
  }

  return (
    <section>
      <h2 className="t-eyebrow" style={{ marginBottom: 6 }}>Custom fields</h2>
      <p style={{ fontSize: 13, color: 'var(--color-ink-400)', margin: '0 0 12px' }}>
        Add your own fields to every {t('record').toLowerCase()} — they appear in the {t('lead').toLowerCase()} details panel.
      </p>

      {fields.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 16, fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--color-ink-200)' }}>
              {['Label', 'Type', 'Options', ''].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--color-ink-400)', fontWeight: 500, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {fields.map(f => (
              <tr key={f.id} style={{ borderBottom: '1px solid var(--color-ink-100)' }}>
                <td style={{ padding: '8px', fontWeight: 500 }}>{f.label}</td>
                <td style={{ padding: '8px', color: 'var(--color-ink-500)' }}>{f.field_type}</td>
                <td style={{ padding: '8px', color: 'var(--color-ink-500)' }}>{f.options.join(', ') || '—'}</td>
                <td style={{ padding: '8px', textAlign: 'right' }}>
                  <button onClick={() => handleDelete(f.id)} title="Delete field" className="dash-icon-btn"
                          style={{ color: 'var(--color-danger)' }}>
                    <Trash2 size={14} strokeWidth={1.5} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <form onSubmit={handleAdd} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <input type="text" value={label} onChange={e => setLabel(e.target.value)} placeholder="Field name" className="drawer-input" style={{ flex: 1, minWidth: 140 }} required />
        <select value={fieldType} onChange={e => setFieldType(e.target.value as RecordFieldType)} className="drawer-input">
          {TYPES.map(ty => <option key={ty} value={ty}>{ty}</option>)}
        </select>
        {fieldType === 'select' && (
          <input type="text" value={options} onChange={e => setOptions(e.target.value)} placeholder="Comma,separated,choices" className="drawer-input" style={{ flex: 1, minWidth: 160 }} />
        )}
        <button type="submit" disabled={saving} className="dash-icon-btn"
                style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 13 }}>
          <Plus size={14} strokeWidth={1.5} /> {saving ? 'Adding…' : 'Add field'}
        </button>
      </form>
      {confirmDialog}
    </section>
  )
}
