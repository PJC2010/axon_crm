'use client'
import { useEffect, useState, useCallback, useRef } from 'react'
import Link from 'next/link'
import { ArrowLeft, RefreshCw, Home, BarChart3, Kanban } from 'lucide-react'
import { getPipeline, getPipelineStats, updateStatus, getLead, getPipelineStages } from '@/lib/api'
import { AuthGuard } from '@/components/AuthGuard'
import type { Lead, PipelineCardLead, PipelineGroup, LeadStatus } from '@/lib/types'
import { KanbanCard } from '@/components/KanbanCard'
import { useKanbanDnd } from '@/hooks/useKanbanDnd'
import { ContactDrawer } from '@/components/ContactDrawer'
import { PipelineAnalytics } from '@/components/PipelineAnalytics'
import { QuickTaskModal } from '@/components/QuickTaskModal'
import { ToastStack, useToast } from '@/components/Toast'
import { WonCelebration, type WonDeal } from '@/components/WonCelebration'

const FALLBACK_STAGES: { key: string; label: string; color: string }[] = [
  { key: 'new',            label: 'New',           color: 'var(--color-ink-300)' },
  { key: 'contacted',      label: 'Contacted',     color: 'var(--color-ocean)' },
  { key: 'qualified',      label: 'Qualified',     color: 'var(--color-accent-300)' },
  { key: 'quote_sent',     label: 'Quote Sent',    color: 'var(--color-gold)' },
  { key: 'won',            label: 'Won',           color: 'var(--color-moss)' },
  { key: 'lost',           label: 'Lost',          color: 'var(--color-danger)' },
  { key: 'not_interested', label: 'Not Interested',color: 'var(--color-ink-200)' },
]

function PipelinePage() {
  const [stages, setStages] = useState<{ key: string; label: string; color: string }[]>(FALLBACK_STAGES)
  const [groups, setGroups] = useState<PipelineGroup>({})
  const [stats, setStats] = useState<Record<string, { count: number; total_value: number }>>({})
  const [loading, setLoading] = useState(true)
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null)
  const [view, setView] = useState<'board' | 'analytics'>('board')
  const [wide, setWide] = useState(false)
  const [quickTaskLead, setQuickTaskLead] = useState<PipelineCardLead | null>(null)
  const [wonDeal, setWonDeal] = useState<WonDeal | null>(null)
  const { toasts, show: showToast, dismiss: dismissToast } = useToast()
  const boardRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const check = () => setWide(window.innerWidth >= 640)
    check()
    window.addEventListener('resize', check)
    return () => window.removeEventListener('resize', check)
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [g, s, stg] = await Promise.all([getPipeline(), getPipelineStats(), getPipelineStages()])
      setGroups(g ?? {})
      setStats(s ?? {})
      if (Array.isArray(stg) && stg.length > 0) {
        setStages(stg.map(st => ({ key: st.key, label: st.label, color: st.color })))
      }
    } catch (e) {
      // Don't let a failed fetch become an unhandled rejection — surface it and
      // keep the board usable with the fallback stages.
      showToast(e instanceof Error ? e.message : 'Failed to load pipeline', 'error')
    } finally {
      setLoading(false)
    }
  }, [showToast])

  useEffect(() => { load() }, [load])

  const moveLead = useCallback(async (lead: PipelineCardLead, stage: string) => {
    if (lead.status === stage) return
    const from = lead.status
    // Optimistic update
    setGroups(prev => {
      const next = { ...prev }
      Object.keys(next).forEach(k => {
        next[k] = next[k].filter(l => l.id !== lead.id)
      })
      // stage_moved_at advances optimistically too, so the cooling chip clears
      // the moment the card lands in its new column.
      next[stage] = [{ ...lead, status: stage as LeadStatus, stage_moved_at: new Date().toISOString() }, ...(next[stage] ?? [])]
      return next
    })
    // Keep the true column counts (rendered from stats, since a column may hold
    // more leads than we render) in sync with the optimistic move.
    setStats(prev => {
      const value = lead.estimated_job_value ?? 0
      const src = prev[from] ?? { count: 0, total_value: 0 }
      const dst = prev[stage] ?? { count: 0, total_value: 0 }
      return {
        ...prev,
        [from]: { count: Math.max(0, src.count - 1), total_value: Math.max(0, src.total_value - value) },
        [stage]: { count: dst.count + 1, total_value: dst.total_value + value },
      }
    })
    // Feedback: celebrate the win (the product's emotional peak), toast the rest.
    if (stage === 'won') {
      setWonDeal({
        value: lead.estimated_job_value,
        label: lead.address || lead.contact_name || lead.owner_name || null,
      })
    } else {
      const label = stages.find(s => s.key === stage)?.label ?? stage
      showToast(`Moved to ${label}`)
    }
    try {
      await updateStatus(lead.id, stage as LeadStatus)
    } catch {
      showToast('Move failed — putting it back', 'error')
      load() // revert on error
    }
  }, [load, stages, showToast])

  async function handleCardClick(card: PipelineCardLead) {
    try {
      const full = await getLead(card.id)
      setSelectedLead(full)
    } catch { /* silently fail */ }
  }

  function handleDrawerStatusChange(id: number, status: LeadStatus) {
    setSelectedLead(prev => prev?.id === id ? { ...prev, status } : prev)
    load()
  }

  // A contact edit or enrichment returns the full updated lead. Reflect it in
  // the open drawer (so the new data shows immediately) and patch the matching
  // board card so its name/phone/score stay in sync.
  function handleDrawerLeadChange(updated: Lead) {
    setSelectedLead(prev => prev?.id === updated.id ? updated : prev)
    setGroups(prev => {
      const next: PipelineGroup = {}
      for (const key of Object.keys(prev)) {
        next[key] = prev[key].map(card => card.id === updated.id ? {
          ...card,
          address: updated.address,
          owner_name: updated.owner_name,
          contact_name: updated.contact_name,
          contact_phone: updated.contact_phone,
          lead_score: updated.lead_score,
          score_grade: updated.score_grade,
          estimated_job_value: updated.estimated_job_value,
          status: updated.status,
          vertical: updated.vertical,
          zip: updated.zip,
        } : card)
      }
      return next
    })
  }

  const { dragItem, draggingId, overStage, onPointerDown, setGhostNode } = useKanbanDnd<PipelineCardLead>({
    getId: lead => lead.id,
    getStage: lead => lead.status,
    onDrop: moveLead,
    onSelect: handleCardClick,
    scrollRef: boardRef,
  })

  const fmtValue = (v: number) =>
    v >= 1000 ? `$${(v / 1000).toFixed(0)}k` : `$${v}`

  return (
    <div style={{ minHeight: '100dvh', background: 'transparent', display: 'flex', flexDirection: 'column' }}>
      <header style={{
        height: 64, padding: wide ? '0 28px' : '0 14px', display: 'flex', alignItems: 'center', gap: wide ? 16 : 8,
        borderBottom: '1px solid var(--color-ink-200)', background: 'var(--color-paper)',
        flexShrink: 0,
      }}>
        <Link href="/dashboard" className="dash-icon-btn" style={{ textDecoration: 'none', color: 'inherit' }}>
          <ArrowLeft size={15} strokeWidth={1.5} />
        </Link>
        <Link href="/home" title="Home" className="dash-icon-btn" style={{ textDecoration: 'none', color: 'inherit' }}>
          <Home size={15} strokeWidth={1.5} />
        </Link>
        <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 600, color: 'var(--color-ink-900)', margin: 0 }}>
          Pipeline
        </h1>
        <div style={{ display: 'flex', gap: 2, background: 'var(--color-ink-100)', borderRadius: 'var(--radius-pill)', padding: 2, marginLeft: wide ? 8 : 0 }}>
          {([['board', Kanban, 'Board'], ['analytics', BarChart3, 'Analytics']] as const).map(([key, Icon, label]) => (
            <button
              key={key}
              onClick={() => setView(key)}
              title={label}
              style={{
                display: 'flex', alignItems: 'center', gap: 5, padding: wide ? '5px 12px' : '6px 10px',
                fontSize: 12, fontWeight: 500, borderRadius: 'var(--radius-pill)', border: 'none', cursor: 'pointer',
                background: view === key ? 'var(--color-paper)' : 'transparent',
                color: view === key ? 'var(--color-ink-900)' : 'var(--color-ink-400)',
                boxShadow: view === key ? 'var(--shadow-card)' : 'none',
                transition: 'all 0.15s',
              }}
            >
              <Icon size={13} strokeWidth={1.5} /> {wide && label}
            </button>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        {view === 'board' && (
          <button onClick={load} className="dash-icon-btn" title="Refresh">
            <RefreshCw size={13} strokeWidth={1.5} className={loading ? 'animate-spin' : ''} />
          </button>
        )}
      </header>

      {view === 'analytics' ? (
        <div style={{ flex: 1, overflowY: 'auto', maxWidth: 900, margin: '0 auto', width: '100%' }}>
          <PipelineAnalytics />
        </div>
      ) : (
        <div ref={boardRef} style={{ flex: 1, overflowX: 'auto', padding: '20px 16px' }}>
          <div style={{ display: 'flex', gap: 12, minWidth: 'max-content', height: '100%' }}>
            {stages.map(stage => {
              const leads = groups[stage.key] ?? []
              const stageStat = stats[stage.key]
              const isOver = overStage === stage.key && dragItem != null && dragItem.status !== stage.key
              return (
                <div
                  key={stage.key}
                  data-stage-key={stage.key}
                  style={{
                    width: 240,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 8,
                    background: isOver ? 'var(--color-surface)' : 'transparent',
                    outline: isOver ? '2px dashed var(--color-accent)' : '2px dashed transparent',
                    outlineOffset: -2,
                    borderRadius: 'var(--radius-card)',
                    transition: 'background 0.15s, outline-color 0.15s',
                    padding: 8,
                    minHeight: 400,
                  }}
                >
                  {/* Column header */}
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{ width: 8, height: 8, borderRadius: '50%', background: stage.color, flexShrink: 0 }} />
                      <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-ink-700)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                        {stage.label}
                      </span>
                    </div>
                    <span style={{ fontSize: 11, color: 'var(--color-ink-400)' }}>
                      {stageStat?.count ?? leads.length}
                      {stageStat?.total_value ? ` · ${fmtValue(stageStat.total_value)}` : ''}
                    </span>
                  </div>

                  {/* Cards */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: 1 }}>
                    {leads.map(lead => (
                      <div
                        key={lead.id}
                        onPointerDown={e => onPointerDown(e, lead)}
                        style={{
                          opacity: draggingId === lead.id ? 0.4 : 1,
                          touchAction: 'pan-x pan-y',
                          WebkitUserSelect: 'none',
                          userSelect: 'none',
                          WebkitTouchCallout: 'none',
                        }}
                      >
                        <KanbanCard lead={lead} onQuickTask={setQuickTaskLead} />
                      </div>
                    ))}
                    {stageStat && stageStat.count > leads.length && (
                      <div style={{ fontSize: 11, color: 'var(--color-ink-400)', textAlign: 'center', padding: '8px 4px' }}>
                        Showing top {leads.length} of {stageStat.count.toLocaleString()} — highest-scoring leads first
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {dragItem && (
        <div
          ref={setGhostNode}
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            width: 224,
            margin: '-20px 0 0 -16px',
            pointerEvents: 'none',
            zIndex: 1000,
            opacity: 0.95,
            willChange: 'transform',
          }}
        >
          <KanbanCard lead={dragItem} ghost />
        </div>
      )}

      <ContactDrawer
        lead={selectedLead}
        onClose={() => setSelectedLead(null)}
        onStatusChange={handleDrawerStatusChange}
        onLeadChange={handleDrawerLeadChange}
        onToast={showToast}
      />

      {quickTaskLead && (
        <QuickTaskModal
          leadId={quickTaskLead.id}
          leadLabel={quickTaskLead.address || quickTaskLead.contact_name || String(quickTaskLead.id)}
          onClose={() => setQuickTaskLead(null)}
          onCreated={msg => showToast(msg, 'success')}
        />
      )}

      <ToastStack toasts={toasts} onDismiss={dismissToast} />
      {wonDeal && <WonCelebration deal={wonDeal} onDone={() => setWonDeal(null)} />}
    </div>
  )
}

export default function PipelinePageGuarded() {
  return <AuthGuard><PipelinePage /></AuthGuard>
}
