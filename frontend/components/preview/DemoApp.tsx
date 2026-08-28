'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import {
  Home, Users, Kanban, Map as MapIcon, ArrowRight, RotateCcw, Zap,
} from 'lucide-react'
import type { Lead, LeadStatus, PipelineCardLead } from '@/lib/types'
import { ProspectCaptureForm } from '@/components/ProspectCaptureForm'
import { ToastStack, useToast } from '@/components/Toast'
import { WonCelebration, type WonDeal } from '@/components/WonCelebration'
import { trackDemoInteraction, trackEvent } from '@/lib/analytics'
import { statusTokens } from '@/lib/gradeColors'
import {
  DEMO_STAGES, SEED_ACTIVITY, makeDemoLeads, makeVisitorLead, openPipelineValue,
  type DemoActivityItem,
} from '@/lib/demoData'
import { DemoDashboard, useCountUpOnce, type DemoTab } from './DemoDashboard'
import { DemoPipeline } from './DemoPipeline'
import { DemoLeads } from './DemoLeads'
import { DemoMap } from './DemoMap'
import { DemoLeadDrawer } from './DemoLeadDrawer'
import { DemoNewLeadModal, type NewLeadInput } from './DemoNewLeadModal'
import { TryChecklist, TRY_ITEMS, type TryKey } from './TryChecklist'

const TABS: { key: DemoTab; label: string; icon: React.ReactNode }[] = [
  { key: 'dashboard', label: 'Dashboard', icon: <Home size={13} strokeWidth={1.5} /> },
  { key: 'leads',     label: 'Leads',     icon: <Users size={13} strokeWidth={1.5} /> },
  { key: 'pipeline',  label: 'Pipeline',  icon: <Kanban size={13} strokeWidth={1.5} /> },
  { key: 'map',       label: 'Map',       icon: <MapIcon size={13} strokeWidth={1.5} /> },
]

function fmtCurrency(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}k`
  return `$${n.toFixed(0)}`
}

function HeroNumber({ value }: { value: number }) {
  const n = useCountUpOnce(value)
  return <>{fmtCurrency(n)}</>
}

/**
 * The interactive live demo behind /preview: a working sample workspace with
 * no login and no API. State lives here; the tabs below render the product's
 * real components (Kanban board + drag hook, lead cards, score explanations,
 * territory map) against it, so everything the visitor touches responds.
 */
export function DemoApp() {
  const [leads, setLeads] = useState<Lead[]>(() => makeDemoLeads())
  const [activity, setActivity] = useState<DemoActivityItem[]>(SEED_ACTIVITY)
  const [tab, setTab] = useState<DemoTab>('dashboard')
  const [mapVisited, setMapVisited] = useState(false)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [showNewLead, setShowNewLead] = useState(false)
  const [wonDeal, setWonDeal] = useState<WonDeal | null>(null)
  const [tried, setTried] = useState<Set<TryKey>>(new Set())
  const [wide, setWide] = useState(false)
  const { toasts, show: showToast, dismiss: dismissToast } = useToast()
  const nextIdRef = useRef(100)
  const completedRef = useRef(false)
  const drawerClearRef = useRef<number | null>(null)

  useEffect(() => {
    const check = () => setWide(window.innerWidth >= 640)
    check()
    window.addEventListener('resize', check)
    return () => window.removeEventListener('resize', check)
  }, [])

  const markTried = useCallback((key: TryKey) => {
    setTried(prev => {
      if (prev.has(key)) return prev
      const next = new Set(prev)
      next.add(key)
      if (next.size === TRY_ITEMS.length && !completedRef.current) {
        completedRef.current = true
        trackEvent('tutorial_complete')
      }
      return next
    })
  }, [])

  const pushActivity = useCallback((item: DemoActivityItem) => {
    setActivity(prev => [item, ...prev])
  }, [])

  // Falls back to the shared status vocabulary for keys the board doesn't
  // carry as a column (e.g. 'converted').
  const stageLabel = (key: string) => DEMO_STAGES.find(s => s.key === key)?.label ?? statusTokens(key).label

  /** All status changes funnel here — board drops and StatusSelect changes. */
  const moveLead = useCallback((id: number, toStage: LeadStatus, source: 'drag' | 'select') => {
    const lead = leads.find(l => l.id === id)
    if (!lead || lead.status === toStage) return
    setLeads(prev => prev.map(l => l.id === id
      ? { ...l, status: toStage, stage_moved_at: new Date().toISOString(), updated_at: new Date().toISOString() }
      : l))
    pushActivity({
      kind: 'move',
      title: lead.address ?? lead.owner_name ?? 'Lead',
      detail: `You moved it to ${stageLabel(toStage)}`,
      time: 'just now',
    })
    // The drag path celebrates/toasts here; the select path already gets its
    // celebration from StatusSelect itself, so don't double up.
    if (source === 'drag') {
      if (toStage === 'won') {
        setWonDeal({ value: lead.estimated_job_value, label: lead.address ?? lead.contact_name ?? lead.owner_name ?? null })
      } else {
        showToast(`Moved to ${stageLabel(toStage)}`)
      }
    }
    markTried(source === 'drag' ? 'drag' : 'status')
    trackDemoInteraction('move_stage', { to: toStage, source })
  }, [leads, markTried, pushActivity, showToast])

  const openLead = useCallback((id: number) => {
    // A close within the last 260ms left a pending clear behind — cancel it,
    // or it would blank the drawer we're about to open.
    if (drawerClearRef.current != null) {
      window.clearTimeout(drawerClearRef.current)
      drawerClearRef.current = null
    }
    setSelectedId(id)
    setDrawerOpen(true)
    markTried('open')
    trackDemoInteraction('open_lead')
  }, [markTried])

  // Close animates out first; the lead clears after so the panel keeps its
  // content while it slides away.
  const closeDrawer = useCallback(() => {
    setDrawerOpen(false)
    drawerClearRef.current = window.setTimeout(() => {
      drawerClearRef.current = null
      setSelectedId(null)
    }, 260)
  }, [])

  const addLead = useCallback((input: NewLeadInput) => {
    const id = nextIdRef.current++
    const lead = makeVisitorLead(id, input)
    setLeads(prev => [lead, ...prev])
    setShowNewLead(false)
    pushActivity({
      kind: 'lead',
      title: lead.address ?? 'New lead',
      detail: 'You added it — scored instantly',
      time: 'just now',
    })
    showToast(`Lead added — scored ${lead.score_grade} (${lead.lead_score})`)
    // Open the visitor's own lead so its "why this score" is the payoff.
    setSelectedId(id)
    setDrawerOpen(true)
    markTried('add')
    trackDemoInteraction('add_lead')
  }, [markTried, pushActivity, showToast])

  const quickTask = useCallback((card: PipelineCardLead) => {
    pushActivity({
      kind: 'task',
      title: `Follow up: ${card.address ?? card.contact_name ?? 'lead'}`,
      detail: 'Task created from the board',
      time: 'just now',
    })
    showToast('Task added — it lands on your Tasks list in the full app')
    trackDemoInteraction('quick_task')
  }, [pushActivity, showToast])

  const goTab = useCallback((next: DemoTab) => {
    setTab(next)
    if (next === 'map') {
      setMapVisited(true)
      markTried('map')
    }
    trackDemoInteraction('view_tab', { tab: next })
  }, [markTried])

  // Stable identity: WonCelebration's auto-dismiss timer re-arms whenever its
  // onDone prop changes, and this page re-renders on every interaction — an
  // inline arrow here would keep the celebration on screen indefinitely.
  const clearWonDeal = useCallback(() => setWonDeal(null), [])

  const resetDemo = useCallback(() => {
    setLeads(makeDemoLeads())
    setActivity(SEED_ACTIVITY)
    setSelectedId(null)
    setDrawerOpen(false)
    showToast('Demo reset — fresh sample data')
    trackDemoInteraction('reset')
  }, [showToast])

  const selected = selectedId != null ? leads.find(l => l.id === selectedId) ?? null : null

  const now = new Date()
  const hour = now.getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
  const dateStr = now.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })

  return (
    <div style={{ minHeight: '100dvh', background: 'transparent', display: 'flex', flexDirection: 'column' }}>
      {/* ── Preview Banner ── */}
      <div style={{
        background: 'linear-gradient(90deg, var(--color-accent), var(--color-ocean-d))',
        color: 'white', textAlign: 'center', padding: '8px 16px', fontSize: 13, fontWeight: 500,
        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 12, flexWrap: 'wrap',
      }}>
        <span>Live demo with sample data — everything here actually works. Drag deals, open scores, add a lead.</span>
        <Link href="/signup" style={{
          color: 'var(--color-accent-700)', background: 'white', textDecoration: 'none',
          padding: '3px 12px', borderRadius: 999, fontWeight: 600, fontSize: 12, whiteSpace: 'nowrap',
        }}>
          Start free trial
        </Link>
      </div>

      {/* ── Top Nav (working tabs) ── */}
      <header style={{
        height: 64, padding: wide ? '0 20px' : '0 10px', background: 'var(--color-paper)',
        borderBottom: '1px solid var(--color-ink-200)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
        position: 'sticky', top: 0, zIndex: 10,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
          <Link href="/" style={{ display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none', color: 'inherit' }}>
            <svg width="26" height="26" viewBox="0 0 32 32" fill="none" aria-hidden="true">
              <mask id="axon-mark-preview">
                <rect width="32" height="32" fill="white" />
                <rect x="2" y="14.5" width="28" height="3" rx="1.5" fill="black" />
                <rect x="14.5" y="2" width="3" height="28" rx="1.5" fill="black" />
              </mask>
              <polygon points="16,5 27,16 16,27 5,16" fill="var(--color-accent)" mask="url(#axon-mark-preview)" />
              <circle cx="16" cy="16" r="1.5" fill="var(--color-ink-900)" />
            </svg>
            <span style={{ fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 600, letterSpacing: '-0.01em', color: 'var(--color-ink-900)' }}>
              Axon
            </span>
          </Link>
          {wide && <span style={{ color: 'var(--color-ink-300)', fontSize: 14 }}>·</span>}
          {wide && <span className="t-eyebrow">Live demo</span>}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 2, flexShrink: 0 }}>
          {TABS.map(item => {
            const active = tab === item.key
            return (
              <button
                key={item.key}
                onClick={() => goTab(item.key)}
                aria-pressed={active}
                style={{
                  display: 'flex', alignItems: 'center', gap: 5, padding: wide ? '8px 12px' : '10px',
                  fontSize: 13, fontWeight: active ? 600 : 400, cursor: 'pointer',
                  background: active ? 'var(--color-surface)' : 'none',
                  border: 'none', borderRadius: 'var(--radius-button)',
                  color: active ? 'var(--color-ink-900)' : 'var(--color-ink-500)',
                  boxShadow: active ? 'var(--shadow-card)' : 'none',
                  fontFamily: 'var(--font-sans)',
                }}
              >
                {item.icon}
                {wide && <span>{item.label}</span>}
              </button>
            )
          })}
          <button
            onClick={resetDemo}
            title="Reset the demo data"
            aria-label="Reset the demo data"
            className="dash-icon-btn"
            style={{ marginLeft: 4 }}
          >
            <RotateCcw size={13} strokeWidth={1.5} />
          </button>
          <Link href="/signup" style={{
            marginLeft: 8, display: 'inline-flex', alignItems: 'center', gap: 6,
            background: 'var(--color-accent)', color: 'var(--text-on-accent)', textDecoration: 'none',
            padding: '8px 14px', borderRadius: 'var(--radius-button)', fontSize: 13, fontWeight: 600,
            whiteSpace: 'nowrap',
          }}>
            Start free{wide && <ArrowRight size={13} strokeWidth={2} />}
          </Link>
        </div>
      </header>

      {/* ── Page Body ── */}
      <div style={{
        flex: 1, maxWidth: tab === 'pipeline' ? 1200 : 960, width: '100%',
        margin: '0 auto', padding: '20px 16px 40px',
      }}>
        {/* ── Hero Greeting (live pipeline value) ── */}
        <div style={{
          borderRadius: 'var(--radius-card)',
          background: 'linear-gradient(135deg, var(--color-accent) 0%, var(--color-ocean-d) 100%)',
          padding: '24px 24px', marginBottom: 14,
          position: 'relative', overflow: 'hidden',
        }}>
          <div style={{ position: 'absolute', top: -30, right: -20, width: 160, height: 160, borderRadius: '50%', background: 'rgba(255,255,255,0.06)' }} />
          <div style={{ position: 'absolute', bottom: -40, right: 60, width: 100, height: 100, borderRadius: '50%', background: 'rgba(255,255,255,0.04)' }} />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12, position: 'relative' }}>
            <div>
              {/* Time-derived text on a statically prerendered page: the baked
                  build-time value will differ at hydration, by design. */}
              <p suppressHydrationWarning style={{ margin: 0, fontFamily: 'var(--font-display)', fontSize: 24, fontWeight: 600, color: 'white', lineHeight: 1.2 }}>
                {greeting}, Pete
              </p>
              <p suppressHydrationWarning style={{ margin: '4px 0 0', fontSize: 13, color: 'rgba(255,255,255,0.65)' }}>{dateStr}</p>
            </div>
            <div style={{ textAlign: 'right' }}>
              <p className="t-eyebrow" style={{ color: 'rgba(255,255,255,0.55)', margin: '0 0 4px' }}>Pipeline Value</p>
              <p className="tabular" style={{ margin: 0, fontSize: 30, fontWeight: 700, color: 'white', lineHeight: 1 }}>
                <HeroNumber value={openPipelineValue(leads)} />
              </p>
            </div>
          </div>
        </div>

        {/* ── Try-it checklist ── */}
        <div style={{ marginBottom: 20 }}>
          <TryChecklist done={tried} />
        </div>

        {/* ── Active tab ── */}
        {tab === 'dashboard' && (
          <DemoDashboard
            leads={leads}
            activity={activity}
            wide={wide}
            onOpen={openLead}
            goTab={goTab}
            onNewLead={() => setShowNewLead(true)}
          />
        )}
        {tab === 'leads' && (
          <DemoLeads
            leads={leads}
            onOpen={openLead}
            onStatusChange={(id, s) => moveLead(id, s, 'select')}
            onNewLead={() => setShowNewLead(true)}
            onFakeAction={msg => showToast(msg)}
          />
        )}
        {tab === 'pipeline' && (
          <DemoPipeline
            leads={leads}
            onMove={(id, to) => moveLead(id, to, 'drag')}
            onOpen={openLead}
            onQuickTask={quickTask}
          />
        )}
        {/* Map stays mounted once visited so the basemap doesn't re-init per visit. */}
        {mapVisited && (
          <div style={{ display: tab === 'map' ? 'block' : 'none' }}>
            <DemoMap leads={leads} onOpen={openLead} />
          </div>
        )}

        {/* ── Marketing sections (dashboard tab only) ── */}
        {tab === 'dashboard' && (
          <>
            <div style={{ marginTop: 32 }}>
              <p className="t-eyebrow" style={{ margin: '0 0 4px' }}>There&apos;s more than the dashboard</p>
              <p style={{ margin: '0 0 14px', fontSize: 13, color: 'var(--color-ink-500)' }}>
                Every plan includes the full pipeline — these ship with your free trial.
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: wide ? 'repeat(3, 1fr)' : '1fr', gap: 12 }}>
                {([
                  { icon: <Kanban size={18} strokeWidth={1.5} />, title: 'Kanban pipeline', desc: 'Drag deals stage to stage; the forecast updates as you go.', action: 'Try it above', go: () => goTab('pipeline') },
                  { icon: <MapIcon size={18} strokeWidth={1.5} />, title: 'Territory map', desc: 'Every scored property on a map of your ZIP codes — plan routes street by street.', action: 'Try it above', go: () => goTab('map') },
                  { icon: <Zap size={18} strokeWidth={1.5} />, title: 'Invoicing & automation', desc: 'Quote, invoice, and get paid — with follow-ups that send themselves.', action: 'Try it free', href: '/signup' },
                ] as const).map(mod => {
                  const inner = (
                    <>
                      <span style={{ color: 'var(--color-accent)', display: 'flex' }}>{mod.icon}</span>
                      <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-ink-900)' }}>{mod.title}</span>
                      <span style={{ fontSize: 12.5, color: 'var(--color-ink-600)', lineHeight: 1.45 }}>{mod.desc}</span>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 600, color: 'var(--color-accent-300)', marginTop: 'auto' }}>
                        {mod.action} <ArrowRight size={12} strokeWidth={1.8} />
                      </span>
                    </>
                  )
                  const cardStyle: React.CSSProperties = {
                    display: 'flex', flexDirection: 'column', gap: 8, padding: '16px 18px',
                    borderRadius: 'var(--radius-card)', background: 'var(--color-surface)',
                    boxShadow: 'var(--shadow-card)', textDecoration: 'none',
                    border: 'none', cursor: 'pointer', textAlign: 'left', fontFamily: 'var(--font-sans)',
                  }
                  return 'href' in mod
                    ? <Link key={mod.title} href={mod.href} style={cardStyle}>{inner}</Link>
                    : <button key={mod.title} onClick={mod.go} style={cardStyle}>{inner}</button>
                })}
              </div>
            </div>

            <div style={{
              marginTop: 32, borderRadius: 'var(--radius-card)', textAlign: 'center',
              background: 'linear-gradient(135deg, var(--color-accent) 0%, var(--color-ocean-d) 100%)',
              padding: '32px 24px',
            }}>
              <p style={{ margin: '0 0 6px', fontFamily: 'var(--font-display)', fontSize: 22, fontWeight: 600, color: 'white' }}>
                This could be your Monday morning.
              </p>
              <p style={{ margin: '0 0 18px', fontSize: 14, color: 'rgba(255,255,255,0.75)' }}>
                Start free — your first ranked property list is minutes away. No credit card.
              </p>
              <Link href="/signup" style={{
                display: 'inline-flex', alignItems: 'center', gap: 8, background: 'white',
                color: 'var(--color-accent-300)', textDecoration: 'none', padding: '12px 26px',
                borderRadius: 'var(--radius-button)', fontSize: 15, fontWeight: 700,
              }}>
                Start free trial <ArrowRight size={15} strokeWidth={2} />
              </Link>
              <div style={{ marginTop: 26, paddingTop: 22, borderTop: '1px solid rgba(255,255,255,0.2)' }}>
                <p style={{ margin: '0 0 12px', fontSize: 13, fontWeight: 600, color: 'rgba(255,255,255,0.85)' }}>
                  Rather see it with your own data first? Leave your email for a personal walkthrough.
                </p>
                <ProspectCaptureForm source="preview" dark />
              </div>
            </div>
          </>
        )}
      </div>

      {/* ── Overlays ── */}
      <DemoLeadDrawer
        lead={selected}
        open={drawerOpen && selected != null}
        onClose={closeDrawer}
        onStatusChange={(id, s) => moveLead(id, s, 'select')}
      />
      {showNewLead && (
        <DemoNewLeadModal onClose={() => setShowNewLead(false)} onCreate={addLead} />
      )}
      {wonDeal && (
        <WonCelebration deal={wonDeal} onDone={clearWonDeal} invoiceHref={null} />
      )}
      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </div>
  )
}
