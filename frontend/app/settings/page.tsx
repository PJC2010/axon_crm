'use client'
import { useEffect, useState, useCallback, FormEvent } from 'react'
import Link from 'next/link'
import { ArrowLeft, Play, Trash2, RefreshCw, Home, XCircle } from 'lucide-react'
import { getSchedules, createSchedule, updateSchedule, deleteSchedule, triggerRun, getPipelineRuns, cancelRun } from '@/lib/api'
import { AuthGuard } from '@/components/AuthGuard'
import type { PipelineSchedule, PipelineRun } from '@/lib/types'

const DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
const VERTICALS = ['', 'epoxy_flooring', 'pool_maintenance', 'solar']
const STATUS_COLOR: Record<string, string> = {
  queued:    'var(--color-ink-400)',
  running:   'var(--color-accent)',
  done:      'var(--color-moss)',
  failed:    'var(--color-danger)',
  cancelled: 'var(--color-gold)',
}

function duration(run: PipelineRun) {
  if (!run.started_at || !run.finished_at) return null
  const ms = new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()
  return `${Math.round(ms / 1000)}s`
}

function SettingsPage() {
  const [schedules, setSchedules] = useState<PipelineSchedule[]>([])
  const [runs, setRuns] = useState<PipelineRun[]>([])
  const [loading, setLoading] = useState(true)

  // Form state
  const [zip, setZip] = useState('')
  const [vertical, setVertical] = useState('')
  const [day, setDay] = useState('monday')
  const [hour, setHour] = useState(6)
  const [saving, setSaving] = useState(false)

  // Manual run state
  const [runZip, setRunZip] = useState('')
  const [runVertical, setRunVertical] = useState('')
  const [triggering, setTriggering] = useState(false)

  const loadData = useCallback(async () => {
    try {
      const [s, r] = await Promise.all([getSchedules(), getPipelineRuns()])
      setSchedules(s)
      setRuns(r)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadData() }, [loadData])

  // Auto-refresh runs when any are running
  useEffect(() => {
    const hasRunning = runs.some(r => r.status === 'running' || r.status === 'queued')
    if (!hasRunning) return
    const id = setInterval(() => getPipelineRuns().then(setRuns), 5000)
    return () => clearInterval(id)
  }, [runs])

  async function handleAddSchedule(e: FormEvent) {
    e.preventDefault()
    if (!zip.trim()) return
    setSaving(true)
    try {
      await createSchedule({ zip: zip.trim(), vertical: vertical || undefined, day_of_week: day, hour })
      setZip('')
      await loadData()
    } finally {
      setSaving(false)
    }
  }

  async function handleToggle(s: PipelineSchedule) {
    await updateSchedule(s.id, { is_active: !s.is_active })
    setSchedules(prev => prev.map(x => x.id === s.id ? { ...x, is_active: !s.is_active } : x))
  }

  async function handleDelete(id: number) {
    if (!confirm('Delete this schedule?')) return
    await deleteSchedule(id)
    setSchedules(prev => prev.filter(s => s.id !== id))
  }

  async function handleTrigger(e: FormEvent) {
    e.preventDefault()
    if (!runZip.trim()) return
    setTriggering(true)
    try {
      await triggerRun(runZip.trim(), runVertical || undefined)
      setRunZip('')
      await getPipelineRuns().then(setRuns)
    } finally {
      setTriggering(false)
    }
  }

  const hasActive = runs.some(r => r.status === 'running' || r.status === 'queued')

  return (
    <div style={{ minHeight: '100vh', background: 'var(--color-paper)' }}>
      <header style={{
        height: 64, padding: '0 28px', display: 'flex', alignItems: 'center', gap: 16,
        borderBottom: '1px solid var(--color-ink-200)', background: 'var(--color-paper)',
      }}>
        <Link href="/dashboard" className="dash-icon-btn" style={{ textDecoration: 'none', color: 'inherit' }}>
          <ArrowLeft size={15} strokeWidth={1.5} />
        </Link>
        <Link href="/home" title="Home" className="dash-icon-btn" style={{ textDecoration: 'none', color: 'inherit' }}>
          <Home size={15} strokeWidth={1.5} />
        </Link>
        <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 600, color: 'var(--color-ink-900)', margin: 0, flex: 1 }}>
          Settings
        </h1>
        {hasActive && (
          <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--color-accent)' }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--color-accent)', animation: 'pulse 1.5s infinite' }} />
            Pipeline running
          </span>
        )}
      </header>

      <div style={{ maxWidth: 760, margin: '0 auto', padding: '28px 20px', display: 'flex', flexDirection: 'column', gap: 32 }}>

        {/* Manual run */}
        <section>
          <h2 className="t-eyebrow" style={{ marginBottom: 12 }}>Run pipeline now</h2>
          <form onSubmit={handleTrigger} style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <input type="text" value={runZip} onChange={e => setRunZip(e.target.value)} placeholder="ZIP code" className="drawer-input" style={{ width: 120 }} required />
            <select value={runVertical} onChange={e => setRunVertical(e.target.value)} className="drawer-input">
              {VERTICALS.map(v => <option key={v} value={v}>{v || 'Default'}</option>)}
            </select>
            <button type="submit" disabled={triggering || !runZip.trim()} style={{
              padding: '0 16px', height: 36, background: 'var(--color-ink-900)', color: 'var(--color-paper)',
              border: 'none', borderRadius: 'var(--radius-pill)', fontSize: 13, cursor: triggering ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: 6,
            }}>
              <Play size={12} />
              {triggering ? 'Starting…' : 'Run'}
            </button>
          </form>
        </section>

        {/* Schedules */}
        <section>
          <h2 className="t-eyebrow" style={{ marginBottom: 12 }}>Scheduled refreshes</h2>

          {schedules.length > 0 && (
            <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 16, fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--color-ink-200)' }}>
                  {['ZIP', 'Vertical', 'Schedule', 'Active', ''].map(h => (
                    <th key={h} style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--color-ink-400)', fontWeight: 500, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {schedules.map(s => (
                  <tr key={s.id} style={{ borderBottom: '1px solid var(--color-ink-100)' }}>
                    <td style={{ padding: '8px', fontWeight: 500 }}>{s.zip}</td>
                    <td style={{ padding: '8px', color: 'var(--color-ink-500)' }}>{s.vertical || '—'}</td>
                    <td style={{ padding: '8px', color: 'var(--color-ink-500)', textTransform: 'capitalize' }}>{s.day_of_week} {s.hour}:00 UTC</td>
                    <td style={{ padding: '8px' }}>
                      <button
                        onClick={() => handleToggle(s)}
                        style={{
                          width: 36, height: 20, borderRadius: 10, border: 'none', cursor: 'pointer',
                          background: s.is_active ? 'var(--color-moss)' : 'var(--color-ink-300)',
                          position: 'relative', transition: 'background 0.2s',
                        }}
                      >
                        <span style={{
                          position: 'absolute', top: 2, left: s.is_active ? 18 : 2,
                          width: 16, height: 16, borderRadius: '50%', background: '#fff',
                          transition: 'left 0.2s',
                        }} />
                      </button>
                    </td>
                    <td style={{ padding: '8px' }}>
                      <button onClick={() => handleDelete(s.id)} className="dash-icon-btn" style={{ padding: 4 }}>
                        <Trash2 size={12} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <form onSubmit={handleAddSchedule} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <input type="text" value={zip} onChange={e => setZip(e.target.value)} placeholder="ZIP" className="drawer-input" style={{ width: 90 }} required />
            <select value={vertical} onChange={e => setVertical(e.target.value)} className="drawer-input">
              {VERTICALS.map(v => <option key={v} value={v}>{v || 'Default'}</option>)}
            </select>
            <select value={day} onChange={e => setDay(e.target.value)} className="drawer-input" style={{ textTransform: 'capitalize' }}>
              {DAYS.map(d => <option key={d} value={d} style={{ textTransform: 'capitalize' }}>{d.charAt(0).toUpperCase() + d.slice(1)}</option>)}
            </select>
            <select value={hour} onChange={e => setHour(Number(e.target.value))} className="drawer-input">
              {Array.from({ length: 24 }, (_, i) => <option key={i} value={i}>{String(i).padStart(2, '0')}:00 UTC</option>)}
            </select>
            <button type="submit" disabled={saving} style={{
              padding: '0 14px', height: 36, background: 'var(--color-surface)', color: 'var(--color-ink-800)',
              border: '1px solid var(--color-ink-200)', borderRadius: 'var(--radius-pill)', fontSize: 13, cursor: saving ? 'not-allowed' : 'pointer',
            }}>
              {saving ? 'Saving…' : 'Add schedule'}
            </button>
          </form>
        </section>

        {/* Run log */}
        <section>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
            <h2 className="t-eyebrow" style={{ margin: 0 }}>Recent runs</h2>
            <button onClick={loadData} className="dash-icon-btn" title="Refresh">
              <RefreshCw size={11} strokeWidth={1.5} />
            </button>
          </div>
          {loading ? (
            <p style={{ fontSize: 13, color: 'var(--color-ink-400)' }}>Loading…</p>
          ) : runs.length === 0 ? (
            <p style={{ fontSize: 13, color: 'var(--color-ink-400)' }}>No runs yet.</p>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--color-ink-200)' }}>
                  {['ZIP', 'Vertical', 'Triggered by', 'Status', 'Started', 'Duration', ''].map(h => (
                    <th key={h} style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--color-ink-400)', fontWeight: 500, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {runs.map(r => (
                  <tr key={r.id} style={{ borderBottom: '1px solid var(--color-ink-100)' }}>
                    <td style={{ padding: '8px', fontWeight: 500 }}>{r.zip}</td>
                    <td style={{ padding: '8px', color: 'var(--color-ink-500)' }}>{r.vertical || '—'}</td>
                    <td style={{ padding: '8px', color: 'var(--color-ink-500)', textTransform: 'capitalize' }}>{r.triggered_by}</td>
                    <td style={{ padding: '8px' }}>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 5, color: STATUS_COLOR[r.status], fontSize: 12, fontWeight: 500 }}>
                        <span style={{ width: 6, height: 6, borderRadius: '50%', background: STATUS_COLOR[r.status] }} />
                        {r.status}
                      </span>
                    </td>
                    <td style={{ padding: '8px', color: 'var(--color-ink-500)' }}>
                      {r.started_at ? new Date(r.started_at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '—'}
                    </td>
                    <td style={{ padding: '8px', color: 'var(--color-ink-500)' }}>{duration(r) ?? '—'}</td>
                    <td style={{ padding: '8px' }}>
                      {(r.status === 'running' || r.status === 'queued') && (
                        <button
                          onClick={async () => {
                            if (!confirm('Stop this pipeline run?')) return
                            try {
                              await cancelRun(r.id)
                              await getPipelineRuns().then(setRuns)
                            } catch (e: unknown) {
                              alert(e instanceof Error ? e.message : 'Failed to cancel')
                            }
                          }}
                          title="Stop run"
                          className="dash-icon-btn"
                          style={{ color: 'var(--color-danger)', display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}
                        >
                          <XCircle size={14} strokeWidth={1.5} />
                          Stop
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </div>
  )
}

export default function SettingsPageGuarded() {
  return <AuthGuard><SettingsPage /></AuthGuard>
}
