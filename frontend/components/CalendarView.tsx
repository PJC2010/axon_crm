'use client'
import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { Check, X, Send, Trash2, MapPin, ArrowUpRight } from 'lucide-react'
import { getAppointments, updateAppointment, deleteAppointment, sendAppointment } from '@/lib/api'
import type { Appointment, AppointmentStatus } from '@/lib/types'

const STATUS_STYLE: Record<AppointmentStatus, { bg: string; text: string; label: string }> = {
  scheduled: { bg: 'var(--color-info-bg)',    text: 'var(--color-info)',    label: 'Scheduled' },
  completed: { bg: 'var(--color-success-bg)', text: 'var(--color-success)', label: 'Completed' },
  cancelled: { bg: 'var(--color-danger-bg)',  text: 'var(--color-danger)',  label: 'Cancelled' },
  no_show:   { bg: 'var(--color-gold-soft)',  text: 'var(--color-gold)',    label: 'No-show' },
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
}

function dayKey(iso: string): string {
  return new Date(iso).toISOString().slice(0, 10)
}

function dayLabel(key: string): string {
  const d = new Date(key + 'T00:00:00')
  return d.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })
}

interface Props {
  reloadKey?: number
  onToast?: (message: string, variant?: 'success' | 'error') => void
}

export function CalendarView({ reloadKey, onToast }: Props) {
  const [appts, setAppts] = useState<Appointment[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const start = new Date(); start.setDate(start.getDate() - 7)
      const end = new Date();   end.setDate(end.getDate() + 60)
      setAppts(await getAppointments({ start: start.toISOString(), end: end.toISOString() }))
    } catch {
      setAppts([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load, reloadKey])

  async function setStatus(a: Appointment, status: AppointmentStatus) {
    try {
      await updateAppointment(a.id, { status })
      load()
    } catch (e) { onToast?.(e instanceof Error ? e.message : 'Update failed', 'error') }
  }

  async function remove(a: Appointment) {
    try { await deleteAppointment(a.id); load() }
    catch (e) { onToast?.(e instanceof Error ? e.message : 'Delete failed', 'error') }
  }

  async function invite(a: Appointment) {
    try {
      const { results } = await sendAppointment(a.id, ['email', 'sms'])
      const sent = Object.entries(results).filter(([, v]) => v === 'sent').map(([k]) => k)
      onToast?.(sent.length ? `Invite sent (${sent.join(', ')})` : `No invite sent: ${Object.values(results).join('; ')}`,
                sent.length ? 'success' : 'error')
    } catch (e) { onToast?.(e instanceof Error ? e.message : 'Send failed', 'error') }
  }

  if (loading) return <p style={{ fontSize: 13, color: 'var(--color-ink-400)' }}>Loading…</p>
  if (appts.length === 0) return <p style={{ fontSize: 14, color: 'var(--color-ink-400)', padding: '12px 0' }}>No appointments scheduled.</p>

  // Group by day in chronological order.
  const groups: Record<string, Appointment[]> = {}
  for (const a of appts) (groups[dayKey(a.starts_at)] ??= []).push(a)
  const days = Object.keys(groups).sort()

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {days.map(day => (
        <div key={day}>
          <p className="t-eyebrow" style={{ margin: '0 0 8px' }}>{dayLabel(day)}</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {groups[day].map(a => {
              const s = STATUS_STYLE[a.status]
              return (
                <div key={a.id} style={{ background: 'var(--color-surface)', borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)', padding: '12px 14px' }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                        <span className="tabular" style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-ink-900)' }}>
                          {fmtTime(a.starts_at)}–{fmtTime(a.ends_at)}
                        </span>
                        <span style={{ padding: '2px 8px', borderRadius: 'var(--radius-pill)', background: s.bg, color: s.text, fontSize: 11, fontWeight: 600 }}>{s.label}</span>
                      </div>
                      <p style={{ margin: '4px 0 0', fontSize: 14, fontWeight: 500, color: 'var(--color-ink-900)' }}>{a.title}</p>
                      {a.location && (
                        <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--color-ink-400)', display: 'flex', alignItems: 'center', gap: 4 }}>
                          <MapPin size={12} strokeWidth={1.5} /> {a.location}
                        </p>
                      )}
                      {a.property_id && (
                        <Link href={`/leads/${a.property_id}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 3, marginTop: 4, fontSize: 12, color: 'var(--color-accent)', textDecoration: 'none' }}>
                          View lead <ArrowUpRight size={12} strokeWidth={1.5} />
                        </Link>
                      )}
                    </div>
                    <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                      {a.status === 'scheduled' && (
                        <>
                          <button onClick={() => invite(a)} className="dash-icon-btn borderless" title="Send calendar invite"><Send size={14} strokeWidth={1.5} /></button>
                          <button onClick={() => setStatus(a, 'completed')} className="dash-icon-btn borderless" title="Mark completed"><Check size={15} strokeWidth={1.5} /></button>
                          <button onClick={() => setStatus(a, 'cancelled')} className="dash-icon-btn borderless" title="Cancel"><X size={15} strokeWidth={1.5} /></button>
                        </>
                      )}
                      <button onClick={() => remove(a)} className="dash-icon-btn borderless" title="Delete"><Trash2 size={14} strokeWidth={1.5} /></button>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
