'use client'
import { useEffect, useState, useCallback } from 'react'
import Link from 'next/link'
import { ArrowLeft, RefreshCw } from 'lucide-react'
import { getPipeline, getPipelineStats, updateStatus } from '@/lib/api'
import { AuthGuard } from '@/components/AuthGuard'
import type { PipelineCardLead, PipelineGroup, LeadStatus } from '@/lib/types'
import { KanbanCard } from '@/components/KanbanCard'

const STAGES: { key: LeadStatus | 'not_interested'; label: string; color: string }[] = [
  { key: 'new',            label: 'New',           color: 'var(--color-ink-300)' },
  { key: 'contacted',      label: 'Contacted',     color: 'var(--color-ocean)' },
  { key: 'qualified',      label: 'Qualified',     color: 'var(--color-accent)' },
  { key: 'quote_sent',     label: 'Quote Sent',    color: 'var(--color-gold)' },
  { key: 'won',            label: 'Won',           color: 'var(--color-moss)' },
  { key: 'lost',           label: 'Lost',          color: 'var(--color-danger)' },
  { key: 'not_interested', label: 'Not Interested',color: 'var(--color-ink-200)' },
]

function PipelinePage() {
  const [groups, setGroups] = useState<PipelineGroup>({})
  const [stats, setStats] = useState<Record<string, { count: number; total_value: number }>>({})
  const [loading, setLoading] = useState(true)
  const [dragLead, setDragLead] = useState<PipelineCardLead | null>(null)
  const [dragOver, setDragOver] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [g, s] = await Promise.all([getPipeline(), getPipelineStats()])
      setGroups(g)
      setStats(s)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  function handleDragStart(lead: PipelineCardLead) {
    setDragLead(lead)
  }

  function handleDragOver(e: React.DragEvent, stage: string) {
    e.preventDefault()
    setDragOver(stage)
  }

  async function handleDrop(e: React.DragEvent, stage: string) {
    e.preventDefault()
    setDragOver(null)
    if (!dragLead || dragLead.status === stage) return
    const lead = dragLead
    setDragLead(null)
    // Optimistic update
    setGroups(prev => {
      const next = { ...prev }
      Object.keys(next).forEach(k => {
        next[k] = next[k].filter(l => l.id !== lead.id)
      })
      next[stage] = [{ ...lead, status: stage as LeadStatus }, ...(next[stage] ?? [])]
      return next
    })
    try {
      await updateStatus(lead.id, stage as LeadStatus)
    } catch {
      load() // revert on error
    }
  }

  const fmtValue = (v: number) =>
    v >= 1000 ? `$${(v / 1000).toFixed(0)}k` : `$${v}`

  return (
    <div style={{ minHeight: '100vh', background: 'var(--color-paper)', display: 'flex', flexDirection: 'column' }}>
      <header style={{
        height: 64, padding: '0 28px', display: 'flex', alignItems: 'center', gap: 16,
        borderBottom: '1px solid var(--color-ink-200)', background: 'var(--color-paper)',
        flexShrink: 0,
      }}>
        <Link href="/dashboard" className="dash-icon-btn" style={{ textDecoration: 'none', color: 'inherit' }}>
          <ArrowLeft size={15} strokeWidth={1.5} />
        </Link>
        <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 600, color: 'var(--color-ink-900)', margin: 0, flex: 1 }}>
          Pipeline
        </h1>
        <button onClick={load} className="dash-icon-btn" title="Refresh">
          <RefreshCw size={13} strokeWidth={1.5} className={loading ? 'animate-spin' : ''} />
        </button>
      </header>

      <div style={{ flex: 1, overflowX: 'auto', padding: '20px 16px' }}>
        <div style={{ display: 'flex', gap: 12, minWidth: 'max-content', height: '100%' }}>
          {STAGES.map(stage => {
            const leads = groups[stage.key] ?? []
            const stageStat = stats[stage.key]
            return (
              <div
                key={stage.key}
                onDragOver={e => handleDragOver(e, stage.key)}
                onDragLeave={() => setDragOver(null)}
                onDrop={e => handleDrop(e, stage.key)}
                style={{
                  width: 240,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 8,
                  background: dragOver === stage.key ? 'var(--color-surface)' : 'transparent',
                  borderRadius: 'var(--radius-card)',
                  transition: 'background 0.15s',
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
                    {leads.length}
                    {stageStat?.total_value ? ` · ${fmtValue(stageStat.total_value)}` : ''}
                  </span>
                </div>

                {/* Cards */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: 1 }}>
                  {leads.map(lead => (
                    <div
                      key={lead.id}
                      draggable
                      onDragStart={() => handleDragStart(lead)}
                      style={{ opacity: dragLead?.id === lead.id ? 0.5 : 1 }}
                    >
                      <KanbanCard lead={lead} onClick={() => {}} />
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export default function PipelinePageGuarded() {
  return <AuthGuard><PipelinePage /></AuthGuard>
}
