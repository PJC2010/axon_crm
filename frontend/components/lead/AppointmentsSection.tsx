'use client'
import { useCallback, useEffect, useState } from 'react'
import { CalendarClock, Plus, Trash2 } from 'lucide-react'
import type { Appointment, AppointmentPage, AppointmentStatus } from '@/lib/types'
import { createAppointment, deleteAppointment, getAppointments, updateAppointment } from '@/lib/api'
import { useEntitlements } from '@/hooks/useEntitlements'

const SECTION_BORDER: React.CSSProperties = { borderBottom: '1px solid var(--color-ink-100)' }
const STATUSES: AppointmentStatus[] = ['scheduled', 'completed', 'cancelled', 'no_show']

function fmtWhen(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

/**
 * Appointments attached to a record. Self-fetching by leadId; renders nothing
 * when the `appointments` module is off.
 */
export function AppointmentsSection({ leadId }: { leadId: number }) {
  const { hasModule, loading: entLoading } = useEntitlements()
  const [page, setPage] = useState<AppointmentPage | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [title, setTitle] = useState('')
  const [startsAt, setStartsAt] = useState('')
  const [durationMin, setDurationMin] = useState(60)
  const [saving, setSaving] = useState(false)

  const load = useCallback(() => {
    getAppointments({ property_id: leadId, page_size: 50 }).then(setPage).catch(() => setPage(null))
  }, [leadId])

  const enabled = hasModule('appointments')
  useEffect(() => { if (enabled) load() }, [enabled, load])

  if (entLoading || !enabled) return null

  const items = page?.items ?? []

  async function handleAdd() {
    if (!title.trim() || !startsAt) return
    setSaving(true)
    try {
      const start = new Date(startsAt)
      const end = new Date(start.getTime() + durationMin * 60_000)
      await createAppointment({
        property_id: leadId,
        title: title.trim(),
        starts_at: start.toISOString(),
        ends_at: end.toISOString(),
      })
      setTitle(''); setStartsAt(''); setDurationMin(60)
      setShowForm(false)
      load()
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Failed to add appointment')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section style={{ padding: '16px 24px', ...SECTION_BORDER }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <CalendarClock size={13} strokeWidth={1.5} style={{ color: 'var(--color-accent)' }} />
          <p className="t-eyebrow" style={{ margin: 0 }}>Appointments</p>
        </div>
        <button onClick={() => setShowForm(s => !s)} className="dash-icon-btn" style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
          <Plus size={12} strokeWidth={1.5} /> Add
        </button>
      </div>

      {page && page.upcoming_count > 0 && page.next_at && (
        <p style={{ margin: '0 0 10px', fontSize: 12, color: 'var(--color-ink-500)' }}>
          Next: <strong style={{ color: 'var(--color-ink-800)' }}>{fmtWhen(page.next_at)}</strong>
          {page.upcoming_count > 1 && <> · {page.upcoming_count} upcoming</>}
        </p>
      )}

      {showForm && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
          <input value={title} onChange={e => setTitle(e.target.value)} placeholder="Title" className="drawer-input" style={{ flex: 1, minWidth: 120 }} />
          <input value={startsAt} onChange={e => setStartsAt(e.target.value)} type="datetime-local" className="drawer-input" style={{ width: 190 }} />
          <select value={durationMin} onChange={e => setDurationMin(Number(e.target.value))} className="drawer-input" style={{ width: 90 }}>
            <option value={30}>30 min</option>
            <option value={60}>1 hour</option>
            <option value={90}>1.5 hours</option>
            <option value={120}>2 hours</option>
          </select>
          <button onClick={handleAdd} disabled={saving} className="dash-icon-btn" style={{ fontSize: 12, color: 'var(--color-accent)' }}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      )}

      {items.length === 0 ? (
        !showForm && <p style={{ margin: 0, fontSize: 12, color: 'var(--color-ink-400)' }}>No appointments yet.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {items.map((a: Appointment) => (
            <div key={a.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
              <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.title}</span>
              <span style={{ color: 'var(--color-ink-400)', fontSize: 12 }}>{fmtWhen(a.starts_at)}</span>
              <select
                value={a.status}
                onChange={async e => { await updateAppointment(a.id, { status: e.target.value as AppointmentStatus }); load() }}
                className="drawer-input"
                style={{ fontSize: 11, width: 104 }}
              >
                {STATUSES.map(s => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
              </select>
              <button
                onClick={async () => { if (confirm('Delete this appointment?')) { await deleteAppointment(a.id); load() } }}
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
