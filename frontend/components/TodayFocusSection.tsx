'use client'
import { useEffect, useState, useCallback } from 'react'
import { AlertTriangle, Clock, Users, Target, CheckCircle2, ArrowRight, Zap } from 'lucide-react'
import Link from 'next/link'
import { getLeads, createTask } from '@/lib/api'
import type { Lead, PipelineCounts, ARSummary } from '@/lib/types'

interface Props {
  taskCounts: PipelineCounts | null
  arSummary: ARSummary | null
  loading: boolean
  onToast: (msg: string, variant?: 'success' | 'error') => void
}

interface FocusItem {
  id: string
  icon: React.ReactNode
  color: string
  bg: string
  border: string
  text: string
  subtext?: string
  actionLabel: string
  onAction?: () => void
  href?: string
}

function offsetDate(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}

export function TodayFocusSection({ taskCounts, arSummary, loading, onToast }: Props) {
  const [staleLeads, setStaleLeads] = useState<Lead[]>([])
  const [hotLeads, setHotLeads] = useState<{ qualified: number; quote_sent: number }>({ qualified: 0, quote_sent: 0 })
  const [creatingFollowUps, setCreatingFollowUps] = useState(false)
  const [staleLoading, setStaleLoading] = useState(true)

  const fetchContextData = useCallback(async () => {
    setStaleLoading(true)
    try {
      const [staleRes, qualRes, quoteRes] = await Promise.allSettled([
        getLeads({ status: 'contacted', sort: 'updated_at', page: 1, page_size: 50 }),
        getLeads({ status: 'qualified', page: 1, page_size: 1 }),
        getLeads({ status: 'quote_sent', page: 1, page_size: 1 }),
      ])
      if (staleRes.status === 'fulfilled') {
        const twoWeeksAgo = new Date(Date.now() - 14 * 86400000).toISOString()
        setStaleLeads(staleRes.value.results.filter(
          (l: Lead) => l.stage_moved_at && l.stage_moved_at < twoWeeksAgo
        ))
      }
      setHotLeads({
        qualified: qualRes.status === 'fulfilled' ? qualRes.value.total : 0,
        quote_sent: quoteRes.status === 'fulfilled' ? quoteRes.value.total : 0,
      })
    } finally {
      setStaleLoading(false)
    }
  }, [])

  useEffect(() => { fetchContextData() }, [fetchContextData])

  async function handleBatchFollowUp() {
    if (staleLeads.length === 0 || creatingFollowUps) return
    setCreatingFollowUps(true)
    const tomorrow = offsetDate(1)
    let created = 0
    try {
      for (const lead of staleLeads.slice(0, 10)) {
        const name = lead.contact_name || lead.owner_name || lead.address || 'lead'
        await createTask({
          title: `Follow up with ${name}`,
          due_date: tomorrow,
          priority: 'high',
          property_id: lead.id,
        })
        created++
      }
      onToast(`Created ${created} follow-up task${created !== 1 ? 's' : ''}`, 'success')
      setStaleLeads([])
    } catch {
      onToast('Failed to create some tasks', 'error')
    } finally {
      setCreatingFollowUps(false)
    }
  }

  if (loading || staleLoading) return null

  const overdue = taskCounts?.overdue ?? 0
  const outstanding = arSummary?.total_outstanding ?? 0
  const hotCount = hotLeads.qualified + hotLeads.quote_sent

  const items: FocusItem[] = []

  if (overdue > 0) {
    items.push({
      id: 'overdue',
      icon: <AlertTriangle size={15} strokeWidth={1.8} />,
      color: 'var(--color-danger)',
      bg: '#FDF2F1',
      border: '#FBCACA',
      text: `${overdue} overdue task${overdue !== 1 ? 's' : ''} need your attention`,
      subtext: 'These were due in the past — clear them to stay on track.',
      actionLabel: 'Review Tasks',
      href: '/tasks',
    })
  }

  if (staleLeads.length > 0) {
    const totalValue = staleLeads.reduce((s, l) => s + (l.estimated_job_value ?? 0), 0)
    items.push({
      id: 'stale',
      icon: <Users size={15} strokeWidth={1.8} />,
      color: 'var(--color-accent)',
      bg: 'var(--color-accent-50)',
      border: 'var(--color-accent-200)',
      text: `${staleLeads.length} lead${staleLeads.length !== 1 ? 's' : ''} haven't heard from you in 2+ weeks`,
      subtext: totalValue > 0 ? `Worth ~$${(totalValue / 1000).toFixed(0)}k in potential work.` : 'Schedule follow-ups to keep them warm.',
      actionLabel: creatingFollowUps ? 'Scheduling…' : 'Schedule Follow-Ups',
      onAction: handleBatchFollowUp,
    })
  }

  if (outstanding > 0) {
    items.push({
      id: 'invoices',
      icon: <Clock size={15} strokeWidth={1.8} />,
      color: 'var(--color-gold)',
      bg: '#FDF8EE',
      border: '#F0D99A',
      text: `$${outstanding >= 1000 ? (outstanding / 1000).toFixed(0) + 'k' : outstanding.toFixed(0)} in unpaid invoices`,
      subtext: 'Send reminders to improve cash flow.',
      actionLabel: 'View Invoices',
      href: '/bookkeeping',
    })
  }

  if (hotCount > 0 && overdue === 0 && staleLeads.length === 0) {
    items.push({
      id: 'hot',
      icon: <Target size={15} strokeWidth={1.8} />,
      color: 'var(--color-moss)',
      bg: '#EEF5EA',
      border: '#C1D9B4',
      text: `${hotCount} hot lead${hotCount !== 1 ? 's' : ''} ready to close`,
      subtext: `${hotLeads.qualified} qualified, ${hotLeads.quote_sent} awaiting quote response.`,
      actionLabel: 'View Pipeline',
      href: '/pipeline',
    })
  }

  if (items.length === 0) {
    return (
      <div style={{
        marginBottom: 20,
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '14px 18px',
        borderRadius: 'var(--radius-card)',
        background: '#EEF5EA',
        border: '1px solid #C1D9B4',
      }}>
        <CheckCircle2 size={18} strokeWidth={1.8} color="var(--color-moss)" />
        <div>
          <p style={{ margin: 0, fontSize: 14, fontWeight: 600, color: 'var(--color-ink-900)' }}>
            You&apos;re all caught up!
          </p>
          <p style={{ margin: 0, fontSize: 12, color: 'var(--color-ink-500)' }}>
            No overdue tasks, no cold leads, no outstanding invoices.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 10 }}>
        <Zap size={13} strokeWidth={2} color="var(--color-accent)" />
        <span className="t-eyebrow">Today&apos;s Focus</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {items.map(item => (
          <div
            key={item.id}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '12px 16px',
              borderRadius: 'var(--radius-card)',
              background: item.bg,
              border: `1px solid ${item.border}`,
              gap: 12,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, flex: 1, minWidth: 0 }}>
              <div style={{
                width: 28, height: 28, borderRadius: 'var(--radius-button)',
                background: item.color,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                flexShrink: 0, marginTop: 1,
              }}>
                <span style={{ color: 'white', display: 'flex' }}>{item.icon}</span>
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <p style={{ margin: '0 0 2px', fontSize: 13.5, fontWeight: 600, color: 'var(--color-ink-900)', lineHeight: 1.35 }}>
                  {item.text}
                </p>
                {item.subtext && (
                  <p style={{ margin: 0, fontSize: 12, color: 'var(--color-ink-500)', lineHeight: 1.4 }}>
                    {item.subtext}
                  </p>
                )}
              </div>
            </div>
            {item.href ? (
              <Link
                href={item.href}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 4,
                  padding: '6px 12px',
                  borderRadius: 'var(--radius-pill)',
                  background: item.color, color: 'white',
                  fontSize: 12, fontWeight: 600,
                  textDecoration: 'none', whiteSpace: 'nowrap', flexShrink: 0,
                }}
              >
                {item.actionLabel} <ArrowRight size={11} strokeWidth={2} />
              </Link>
            ) : (
              <button
                onClick={item.onAction}
                disabled={creatingFollowUps}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 4,
                  padding: '6px 12px',
                  borderRadius: 'var(--radius-pill)',
                  background: creatingFollowUps ? 'var(--color-ink-400)' : item.color,
                  color: 'white', border: 'none',
                  fontSize: 12, fontWeight: 600,
                  cursor: creatingFollowUps ? 'not-allowed' : 'pointer',
                  whiteSpace: 'nowrap', flexShrink: 0,
                }}
              >
                {item.actionLabel}
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
