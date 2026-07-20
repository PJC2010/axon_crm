'use client'
import { useEffect, useState, useCallback, FormEvent } from 'react'
import Link from 'next/link'
import { ArrowLeft, Play, Trash2, RefreshCw, Home, XCircle, Zap, Plus } from 'lucide-react'
import { getSchedules, createSchedule, updateSchedule, deleteSchedule, triggerRun, getPipelineRuns, cancelRun, rescoreZip, rescoreAll, getWorkflows, updateWorkflow, deleteWorkflow, seedWorkflowDefaults } from '@/lib/api'
import { AuthGuard } from '@/components/AuthGuard'
import { AutomationTemplates } from '@/components/AutomationTemplates'
import { WorkflowRuleForm, describeTrigger } from '@/components/WorkflowRuleForm'
import { ConnectionsSection } from '@/components/ConnectionsSection'
import { StripeConnectSection } from '@/components/StripeConnectSection'
import { CallTrackingSection } from '@/components/CallTrackingSection'
import { BillingSection } from '@/components/BillingSection'
import { BusinessProfileSection } from '@/components/BusinessProfileSection'
import { QuickBooksExportSection } from '@/components/QuickBooksExportSection'
import { CustomFieldsSettings } from '@/components/CustomFieldsSettings'
import { MessageTemplatesSettings } from '@/components/MessageTemplatesSettings'
import { ImportOrdersModal } from '@/components/ImportOrdersModal'
import { RescoreSection } from '@/components/RescoreSection'
import { useEntitlements } from '@/hooks/useEntitlements'
import { useTerminology } from '@/hooks/useTerminology'
import type { PipelineSchedule, PipelineRun, WorkflowRule } from '@/lib/types'

const DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
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

// Plain-language outcome line for a finished run ("what did this run
// produce/cost"), from the summary the scheduler stamps into result_json.
function runSummary(run: PipelineRun): string | null {
  const s = run.result_json?.summary as
    | { properties_scored?: number; grade_a?: number; grade_b?: number
        skip_traces_used?: number; storm_hits?: number }
    | undefined
  if (!s || s.properties_scored == null) return null
  const parts = [
    `${s.properties_scored.toLocaleString()} scored`,
    `${s.grade_a ?? 0} A · ${s.grade_b ?? 0} B`,
  ]
  if (s.skip_traces_used) parts.push(`${s.skip_traces_used} skip-trace${s.skip_traces_used === 1 ? '' : 's'} used`)
  if (s.storm_hits) parts.push(`${s.storm_hits} storm hit${s.storm_hits === 1 ? '' : 's'}`)
  return parts.join(' · ')
}

function SettingsPage() {
  const { hasModule } = useEntitlements()
  const { categories } = useTerminology()
  const [schedules, setSchedules] = useState<PipelineSchedule[]>([])
  const [runs, setRuns] = useState<PipelineRun[]>([])
  const [workflows, setWorkflows] = useState<WorkflowRule[]>([])
  const [loading, setLoading] = useState(true)
  const [showWfForm, setShowWfForm] = useState(false)
  const [seeding, setSeeding] = useState(false)

  // Form state
  const [zip, setZip] = useState('')
  const [vertical, setVertical] = useState('')
  const [day, setDay] = useState('monday')
  const [hour, setHour] = useState(6)
  const [topN, setTopN] = useState('')
  const [nearAddress, setNearAddress] = useState('')
  const [radiusMi, setRadiusMi] = useState('')
  const [saving, setSaving] = useState(false)

  // Manual run state
  const [runZip, setRunZip] = useState('')
  const [runVertical, setRunVertical] = useState('')
  const [runTopN, setRunTopN] = useState('')
  const [runNearAddress, setRunNearAddress] = useState('')
  const [runRadiusMi, setRunRadiusMi] = useState('')
  const [triggering, setTriggering] = useState(false)
  const [rescoring, setRescoring] = useState(false)
  const [rescoringAll, setRescoringAll] = useState(false)

  const loadData = useCallback(async () => {
    try {
      // Fetch independently so a 403 from a module the account lacks (prospecting
      // schedules/runs, automation workflows) doesn't blank out the rest.
      const [s, r, w] = await Promise.allSettled([getSchedules(), getPipelineRuns(), getWorkflows()])
      if (s.status === 'fulfilled') setSchedules(s.value)
      if (r.status === 'fulfilled') setRuns(r.value)
      if (w.status === 'fulfilled') setWorkflows(w.value)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadData() }, [loadData])

  // Auto-refresh runs when any are running
  useEffect(() => {
    const hasRunning = runs.some(r => r.status === 'running' || r.status === 'queued')
    if (!hasRunning) return
    const id = setInterval(() => getPipelineRuns().then(setRuns).catch(() => {}), 5000)
    return () => clearInterval(id)
  }, [runs])

  function buildControls(n: string, addr: string, radius: string) {
    const controls: { top_n?: number; center_address?: string; radius_mi?: number } = {}
    if (n.trim()) controls.top_n = Number(n)
    if (addr.trim() && radius.trim()) {
      controls.center_address = addr.trim()
      controls.radius_mi = Number(radius)
    }
    return controls
  }

  async function handleAddSchedule(e: FormEvent) {
    e.preventDefault()
    if (!zip.trim()) return
    setSaving(true)
    try {
      await createSchedule({
        zip: zip.trim(), vertical: vertical || undefined, day_of_week: day, hour,
        ...buildControls(topN, nearAddress, radiusMi),
      })
      setZip(''); setTopN(''); setNearAddress(''); setRadiusMi('')
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
      await triggerRun({ zip: runZip.trim() }, runVertical || undefined,
        buildControls(runTopN, runNearAddress, runRadiusMi))
      setRunZip(''); setRunTopN(''); setRunNearAddress(''); setRunRadiusMi('')
      await getPipelineRuns().then(setRuns)
    } finally {
      setTriggering(false)
    }
  }

  const hasActive = runs.some(r => r.status === 'running' || r.status === 'queued')

  return (
    <div style={{ minHeight: '100vh', background: 'transparent' }}>
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

        {/* The account's own Axon subscription (plan, trial, upgrades). */}
        <BillingSection />

        {/* Business name + review link (powers the review-request automation). */}
        <BusinessProfileSection />

        {hasModule('prospecting') && (
        <>
        {/* Manual run */}
        <section>
          <h2 className="t-eyebrow" style={{ marginBottom: 12 }}>Run pipeline now</h2>
          <form onSubmit={handleTrigger} style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <input type="text" value={runZip} onChange={e => setRunZip(e.target.value)} placeholder="ZIP code" className="drawer-input" style={{ width: 120 }} required />
            <select value={runVertical} onChange={e => setRunVertical(e.target.value)} className="drawer-input">
              <option value="">Default</option>
              {categories.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
            <input type="number" min={1} value={runTopN} onChange={e => setRunTopN(e.target.value)} placeholder="Leads/run" title="Cap leads enriched per run (saves API cost). Blank = whole ZIP." className="drawer-input" style={{ width: 110 }} />
            <input type="text" value={runNearAddress} onChange={e => setRunNearAddress(e.target.value)} placeholder="Near address (optional)" title="Only enrich homes within the radius of this address" className="drawer-input" style={{ width: 200 }} />
            <input type="number" min={0} step={0.5} value={runRadiusMi} onChange={e => setRunRadiusMi(e.target.value)} placeholder="mi" title="Radius in miles from the address above" className="drawer-input" style={{ width: 70 }} disabled={!runNearAddress.trim()} />
            <button type="submit" disabled={triggering || !runZip.trim()} style={{
              padding: '0 16px', height: 36, background: 'var(--color-ink-900)', color: 'var(--color-paper)',
              border: 'none', borderRadius: 'var(--radius-pill)', fontSize: 13, cursor: triggering ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: 6,
            }}>
              <Play size={12} />
              {triggering ? 'Starting…' : 'Run'}
            </button>
            <button
              type="button"
              disabled={rescoring || !runZip.trim()}
              onClick={async () => {
                if (!runZip.trim()) return
                setRescoring(true)
                try {
                  const result = await rescoreZip(runZip.trim(), runVertical || undefined)
                  alert(`Scored ${result.scored} leads in ZIP ${result.zip}`)
                } catch (e: unknown) {
                  alert(e instanceof Error ? e.message : 'Rescore failed')
                } finally {
                  setRescoring(false)
                }
              }}
              style={{
                padding: '0 16px', height: 36, background: 'var(--color-accent)', color: 'white',
                border: 'none', borderRadius: 'var(--radius-pill)', fontSize: 13, cursor: rescoring ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: 6,
              }}
            >
              {rescoring ? 'Scoring…' : 'Rescore Only'}
            </button>
            <button
              type="button"
              disabled={rescoringAll}
              onClick={async () => {
                if (!confirm('Rescore all leads across all ZIPs? This may take a minute.')) return
                setRescoringAll(true)
                try {
                  const result = await rescoreAll()
                  alert(`Scored ${result.scored} leads across ${result.zips} ZIP codes`)
                } catch (e: unknown) {
                  alert(e instanceof Error ? e.message : 'Rescore failed')
                } finally {
                  setRescoringAll(false)
                }
              }}
              style={{
                padding: '0 16px', height: 36, background: 'var(--color-moss)', color: 'white',
                border: 'none', borderRadius: 'var(--radius-pill)', fontSize: 13, cursor: rescoringAll ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: 6,
              }}
            >
              {rescoringAll ? 'Scoring all…' : 'Rescore All ZIPs'}
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
                  {['ZIP', 'Vertical', 'Limit', 'Schedule', 'Active', ''].map(h => (
                    <th key={h} style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--color-ink-400)', fontWeight: 500, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {schedules.map(s => (
                  <tr key={s.id} style={{ borderBottom: '1px solid var(--color-ink-100)' }}>
                    <td style={{ padding: '8px', fontWeight: 500 }}>{s.zip}</td>
                    <td style={{ padding: '8px', color: 'var(--color-ink-500)' }}>{s.vertical || '—'}</td>
                    <td style={{ padding: '8px', color: 'var(--color-ink-500)' }}>
                      {[s.top_n ? `top ${s.top_n}` : null,
                        s.center_address && s.radius_mi ? `${s.radius_mi}mi` : null]
                        .filter(Boolean).join(' · ') || '—'}
                    </td>
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
              <option value="">Default</option>
              {categories.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
            <select value={day} onChange={e => setDay(e.target.value)} className="drawer-input" style={{ textTransform: 'capitalize' }}>
              {DAYS.map(d => <option key={d} value={d} style={{ textTransform: 'capitalize' }}>{d.charAt(0).toUpperCase() + d.slice(1)}</option>)}
            </select>
            <select value={hour} onChange={e => setHour(Number(e.target.value))} className="drawer-input">
              {Array.from({ length: 24 }, (_, i) => <option key={i} value={i}>{String(i).padStart(2, '0')}:00 UTC</option>)}
            </select>
            <input type="number" min={1} value={topN} onChange={e => setTopN(e.target.value)} placeholder="Leads/run" title="Cap leads enriched per run (saves API cost). Blank = whole ZIP." className="drawer-input" style={{ width: 110 }} />
            <input type="text" value={nearAddress} onChange={e => setNearAddress(e.target.value)} placeholder="Near address (optional)" title="Only enrich homes within the radius of this address" className="drawer-input" style={{ width: 180 }} />
            <input type="number" min={0} step={0.5} value={radiusMi} onChange={e => setRadiusMi(e.target.value)} placeholder="mi" title="Radius in miles from the address above" className="drawer-input" style={{ width: 70 }} disabled={!nearAddress.trim()} />
            <button type="submit" disabled={saving} style={{
              padding: '0 14px', height: 36, background: 'var(--color-surface)', color: 'var(--color-ink-800)',
              border: '1px solid var(--color-ink-200)', borderRadius: 'var(--radius-pill)', fontSize: 13, cursor: saving ? 'not-allowed' : 'pointer',
            }}>
              {saving ? 'Saving…' : 'Add schedule'}
            </button>
          </form>
        </section>
        </>
        )}

        {/* Workflow rules */}
        {hasModule('automation') && (
        <section>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Zap size={14} strokeWidth={1.5} style={{ color: 'var(--color-accent)' }} />
              <h2 className="t-eyebrow" style={{ margin: 0 }}>Workflow automations</h2>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <select
                value=""
                onChange={async (e) => {
                  const v = e.target.value
                  if (!v) return
                  setSeeding(true)
                  try {
                    await seedWorkflowDefaults(v)
                    const w = await getWorkflows()
                    setWorkflows(w)
                  } catch (err: unknown) {
                    alert(err instanceof Error ? err.message : 'Failed to seed defaults')
                  } finally {
                    setSeeding(false)
                  }
                }}
                className="drawer-input"
                style={{ fontSize: 12 }}
                disabled={seeding}
              >
                <option value="">{seeding ? 'Seeding…' : 'Seed defaults…'}</option>
                <option value="epoxy_flooring">Epoxy Flooring</option>
                <option value="pool_maintenance">Pool Maintenance</option>
                <option value="solar">Solar</option>
                <option value="roofing">Roofing</option>
                <option value="hvac">HVAC</option>
                <option value="fencing">Fencing</option>
                <option value="landscaping">Landscaping</option>
                <option value="pressure_washing">Pressure Washing</option>
              </select>
              <button onClick={() => setShowWfForm(!showWfForm)} className="dash-icon-btn" style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
                <Plus size={12} strokeWidth={1.5} /> New rule
              </button>
            </div>
          </div>

          <AutomationTemplates
            workflows={workflows}
            onWorkflowsChange={setWorkflows}
          />

          {showWfForm && (
            <WorkflowRuleForm
              onCreated={async () => {
                setShowWfForm(false)
                const w = await getWorkflows()
                setWorkflows(w)
              }}
              onCancel={() => setShowWfForm(false)}
            />
          )}

          {workflows.length > 0 ? (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--color-ink-200)' }}>
                  {['Name', 'Trigger', 'Action', 'Vertical', 'Active', ''].map(h => (
                    <th key={h} style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--color-ink-400)', fontWeight: 500, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {workflows.map(w => (
                  <tr key={w.id} style={{ borderBottom: '1px solid var(--color-ink-100)' }}>
                    <td style={{ padding: '8px', fontWeight: 500 }}>{w.name}</td>
                    <td style={{ padding: '8px', color: 'var(--color-ink-500)', fontSize: 12 }}>
                      {describeTrigger(w)}
                    </td>
                    <td style={{ padding: '8px', color: 'var(--color-ink-500)', fontSize: 12 }}>
                      {w.action_config.title || w.action_type}
                      {w.action_config.due_days_offset != null && ` (${w.action_config.due_days_offset}d)`}
                    </td>
                    <td style={{ padding: '8px', color: 'var(--color-ink-500)' }}>{w.vertical || 'All'}</td>
                    <td style={{ padding: '8px' }}>
                      <button
                        onClick={async () => {
                          await updateWorkflow(w.id, { is_active: !w.is_active })
                          setWorkflows(prev => prev.map(x => x.id === w.id ? { ...x, is_active: !w.is_active } : x))
                        }}
                        style={{
                          width: 36, height: 20, borderRadius: 10, border: 'none', cursor: 'pointer',
                          background: w.is_active ? 'var(--color-moss)' : 'var(--color-ink-300)',
                          position: 'relative', transition: 'background 0.2s',
                        }}
                      >
                        <span style={{
                          position: 'absolute', top: 2, left: w.is_active ? 18 : 2,
                          width: 16, height: 16, borderRadius: '50%', background: '#fff',
                          transition: 'left 0.2s',
                        }} />
                      </button>
                    </td>
                    <td style={{ padding: '8px' }}>
                      <button
                        onClick={async () => {
                          if (!confirm(`Delete rule "${w.name}"?`)) return
                          await deleteWorkflow(w.id)
                          setWorkflows(prev => prev.filter(x => x.id !== w.id))
                        }}
                        className="dash-icon-btn"
                        style={{ padding: 4 }}
                      >
                        <Trash2 size={12} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p style={{ fontSize: 13, color: 'var(--color-ink-400)' }}>
              No workflow rules yet. Use &quot;Seed defaults&quot; to get started with recommended automations for your vertical.
            </p>
          )}
        </section>
        )}

        {/* Custom fields (generic record model) */}
        <CustomFieldsSettings />

        <MessageTemplatesSettings />

        {hasModule('orders') && (
          <section>
            <h2 className="t-eyebrow" style={{ marginBottom: 6 }}>Orders</h2>
            <p style={{ fontSize: 13, color: 'var(--color-ink-400)', margin: '0 0 12px' }}>
              Import your Square or Shopify order history. Customers are matched by email and their
              purchase history feeds RFM scoring automatically.
            </p>
            <ImportOrdersModal />
          </section>
        )}

        <RescoreSection />

        {/* Online payments (Stripe Connect) — rides the invoicing module */}
        {hasModule('invoicing') && <StripeConnectSection />}

        {/* Call tracking (Twilio tracking number + forwarding) */}
        {hasModule('calls') && <CallTrackingSection />}

        {/* One-way QuickBooks-format exports (bookkeeper escape hatch). */}
        {(hasModule('invoicing') || hasModule('bookkeeping')) && <QuickBooksExportSection />}

        {/* Connected accounts / integrations (Meta CSV insights) — granted by no
            named plan; only per-account overrides re-enable it. */}
        {hasModule('marketing') && <ConnectionsSection />}

        {/* Run log */}
        {hasModule('prospecting') && (
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
                  {['ZIP', 'Vertical', 'Triggered by', 'Status', 'Results', 'Started', 'Duration', ''].map(h => (
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
                    <td style={{ padding: '8px', color: 'var(--color-ink-500)', fontSize: 12 }}>{runSummary(r) ?? '—'}</td>
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
        )}
      </div>
    </div>
  )
}

export default function SettingsPageGuarded() {
  return <AuthGuard><SettingsPage /></AuthGuard>
}
