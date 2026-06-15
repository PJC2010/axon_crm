'use client'
import { useEffect, useState } from 'react'
import { CalendarPlus } from 'lucide-react'
import { createAppointment, getTeam } from '@/lib/api'
import type { TeamMember } from '@/lib/types'

const DURATIONS = [30, 60, 90, 120]

function defaultStart(): string {
  // Next top of the hour, formatted for <input type="datetime-local"> (local time).
  const d = new Date()
  d.setMinutes(0, 0, 0)
  d.setHours(d.getHours() + 1)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

interface Props {
  prefillLeadId?: number
  prefillTitle?: string
  prefillLocation?: string
  onCreated?: () => void
  onToast?: (message: string, variant?: 'success' | 'error') => void
}

export function AppointmentForm({ prefillLeadId, prefillTitle, prefillLocation, onCreated, onToast }: Props) {
  const [title, setTitle] = useState(prefillTitle ?? '')
  const [start, setStart] = useState(defaultStart)
  const [duration, setDuration] = useState(60)
  const [location, setLocation] = useState(prefillLocation ?? '')
  const [assignedTo, setAssignedTo] = useState<string>('')
  const [notes, setNotes] = useState('')
  const [team, setTeam] = useState<TeamMember[]>([])
  const [saving, setSaving] = useState(false)

  useEffect(() => { getTeam().then(setTeam).catch(() => {}) }, [])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!title.trim() || !start) return
    setSaving(true)
    try {
      const startsAt = new Date(start)                       // local → absolute
      const endsAt = new Date(startsAt.getTime() + duration * 60_000)
      await createAppointment({
        property_id: prefillLeadId ?? null,
        assigned_to: assignedTo ? Number(assignedTo) : null,
        title: title.trim(),
        location: location.trim() || null,
        starts_at: startsAt.toISOString(),
        ends_at: endsAt.toISOString(),
        notes: notes.trim() || null,
      })
      onToast?.('Appointment scheduled', 'success')
      setTitle(prefillTitle ?? ''); setNotes(''); setLocation(prefillLocation ?? '')
      onCreated?.()
    } catch (err) {
      onToast?.(err instanceof Error ? err.message : 'Failed to schedule', 'error')
    } finally { setSaving(false) }
  }

  return (
    <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 10, background: 'white', padding: 16, borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)' }}>
      <input
        value={title}
        onChange={e => setTitle(e.target.value)}
        placeholder="Appointment title (e.g. Roof inspection)"
        style={INPUT}
        required
      />
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <input type="datetime-local" value={start} onChange={e => setStart(e.target.value)} style={{ ...INPUT, flex: 2, minWidth: 200 }} required />
        <select value={duration} onChange={e => setDuration(Number(e.target.value))} className="select-field" style={{ flex: 1, minWidth: 110 }}>
          {DURATIONS.map(d => <option key={d} value={d}>{d} min</option>)}
        </select>
      </div>
      <input value={location} onChange={e => setLocation(e.target.value)} placeholder="Location (optional)" style={INPUT} />
      <select value={assignedTo} onChange={e => setAssignedTo(e.target.value)} className="select-field">
        <option value="">Unassigned</option>
        {team.map(m => <option key={m.id} value={m.id}>{m.username}</option>)}
      </select>
      <textarea value={notes} onChange={e => setNotes(e.target.value)} placeholder="Notes (optional)" rows={2} style={{ ...INPUT, resize: 'vertical' }} />
      <button
        type="submit"
        disabled={saving || !title.trim()}
        style={{
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8,
          minHeight: 44, borderRadius: 'var(--radius-pill)', border: 'none',
          background: 'var(--color-accent)', color: 'white', fontSize: 14, fontWeight: 600,
          cursor: saving ? 'default' : 'pointer', opacity: saving ? 0.7 : 1,
        }}
      >
        <CalendarPlus size={15} strokeWidth={1.8} />
        {saving ? 'Scheduling…' : 'Schedule appointment'}
      </button>
    </form>
  )
}

const INPUT: React.CSSProperties = {
  fontSize: 14, padding: '10px 12px', borderRadius: 'var(--radius-input)',
  border: '1px solid var(--color-ink-200)', background: 'var(--color-paper)',
  color: 'var(--color-ink-900)', fontFamily: 'var(--font-sans)', outline: 'none', width: '100%',
}
