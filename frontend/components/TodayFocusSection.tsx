'use client'
import { useEffect, useState, useCallback } from 'react'
import { AlertTriangle, Clock, Users, Target, CheckCircle2, ArrowRight, Zap, TrendingDown } from 'lucide-react'
import Link from 'next/link'
import { getLeads, createTask, getPipelineAlerts } from '@/lib/api'
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
  const [stuckCount, setStuckCount] = useState(0)
  const [stuckValue, setStuckValue] = useState(0)
  const [creatingFollowUps, setCreatingFollowUps] = useState(false)
  const [staleLoading, setStaleLoading] = useState(true)

  const fetchContextData = useCallback(async () => {
    setStaleLoading(true)
    try {
      const [staleRes, qualRes, quoteRes, alertsRes] = await Promise.allSettled([
        getLeads({ status: 'contacted', sort: 'updated_at', page: 1, page_size: 50 }),
        getLeads({ status: 'qualified', page: 1, page_size: 1 }),
        getLeads({ status: 'quote_sent', page: 1, page_size: 1 }),
        getPipelineAlerts(),
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
      setStuckCount(alertsRes.status === 'fulfilled' ? alertsRes.value.stuck_deals.count : 0)
      setStuckValue(alertsRes.status === 'fulfilled'
        ? alertsRes.value.stuck_deals.items.reduce((s, d) => s + (d.estimated_job_value ?? 0), 0)
        : 0)
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
  const overdueAR = arSummary?.total_overdue ?? 0
  const overdueCount = arSummary?.overdue_count ?? 0
  const hotCount = hotLeads.qualified + hotLeads.quote_sent

  // Single deduplicated, priority-ordered list (problems before opportunities),
  // capped below. Each concern appears exactly once.
  const items: FocusItem[] = []

  // 1. Overdue tasks
  if (overdue > 0) {
    items.push({
      id: 'overdue',
      icon: <AlertTriangle size={15} strokeWidth={1.8} />,
      color: 'var(--color-danger)',
      bg: 'var(--color-danger-bg)',
      border: 'var(--color-danger)',
      text: `${overdue} overdue task${overdue !== 1 ? 's' : ''} need your attention`,
      subtext: 'These were due in the past — clear them to stay on track.',
      actionLabel: 'Review Tasks',
      href: '/tasks',
    })
  }

  // 2. Overdue / outstanding invoices (money owed to you) — lead with the overdue slice
  if (overdueAR > 0) {
    items.push({
      id: 'invoices',
      icon: <Clock size={15} strokeWidth={1.8} />,
      color: 'var(--color-danger)',
      bg: 'var(--color-danger-bg)',
      border: 'var(--color-danger)',
      text: `${fmtMoney(overdueAR)} in overdue invoices`,
      subtext: `${overdueCount} invoice${overdueCount !== 1 ? 's' : ''} past due — send reminders to improve cash flow.`,
      actionLabel: 'View Invoices',
      href: '/bookkeeping',
    })
  } else if (outstanding > 0) {
    items.push({
      id: 'invoices',
      icon: <Clock size={15} strokeWidth={1.8} />,
      color: 'var(--color-gold)',
      bg: 'var(--color-warning-bg)',
      border: 'var(--color-warning)',
      text: `${fmtMoney(outstanding)} in unpaid invoices`,
      subtext: 'Send reminders to improve cash flow.',
      actionLabel: 'View Invoices',
      href: '/bookkeeping',
    })
  }

  // 3. Stuck deals (folded in from the old Command Center)
  if (stuckCount > 0) {
    items.push({
      id: 'stuck',
      icon: <TrendingDown size={15} strokeWidth={1.8} />,
      color: 'var(--color-gold)',
      bg: 'var(--color-warning-bg)',
      border: 'var(--color-warning)',
      // Loss framing: money at risk beats a bare count for this ICP.
      text: stuckValue > 0
        ? `≈ ${fmtMoney(stuckValue)} stuck in stage — ${stuckCount} deal${stuckCount !== 1 ? 's' : ''} not moving`
        : `${stuckCount} deal${stuckCount !== 1 ? 's' : ''} stuck in stage`,
      subtext: 'These have sat too long — nudge them forward before they go cold.',
      actionLabel: 'View Pipeline',
      href: '/pipeline',
    })
  }

  // 4. Stale / cooling leads
  if (staleLeads.length > 0) {
    const totalValue = staleLeads.reduce((s, l) => s + (l.estimated_job_value ?? 0), 0)
    items.push({
      id: 'stale',
      icon: <Users size={15} strokeWidth={1.8} />,
      color: 'var(--color-accent)',
      bg: 'var(--color-accent-50)',
      border: 'var(--color-accent-200)',
      // Loss framing: lead with the dollars going cold, not the lead count.
      text: totalValue > 0
        ? `≈ ${fmtMoney(totalValue)} in work going cold — ${staleLeads.length} lead${staleLeads.length !== 1 ? 's' : ''} untouched for 2+ weeks`
        : `${staleLeads.length} lead${staleLeads.length !== 1 ? 's' : ''} haven't heard from you in 2+ weeks`,
      subtext: 'One tap schedules the follow-ups before they go cold for good.',
      actionLabel: creatingFollowUps ? 'Scheduling…' : 'Schedule Follow-Ups',
      onAction: handleBatchFollowUp,
    })
  }

  // 5. Hot leads ready to close (opportunity — only when nothing urgent is pending)
  if (hotCount > 0 && overdue === 0 && staleLeads.length === 0) {
    items.push({
      id: 'hot',
      icon: <Target size={15} strokeWidth={1.8} />,
      color: 'var(--color-moss)',
      bg: 'var(--color-success-bg)',
      border: 'var(--color-success)',
      text: `${hotCount} hot lead${hotCount !== 1 ? 's' : ''} ready to close`,
      subtext: `${hotLeads.qualified} qualified, ${hotLeads.quote_sent} awaiting quote response.`,
      actionLabel: 'View Pipeline',
      href: '/pipeline',
    })
  }

  // Cap the overview list; deeper detail lives on the linked pages.
  const MAX_ITEMS = 5
  const overflow = items.length - MAX_ITEMS
  const visibleItems = items.slice(0, MAX_ITEMS)

  if (items.length === 0) {
    return (
      <div style={{
        marginBottom: 20,
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '14px 18px',
        borderRadius: 'var(--radius-card)',
        background: 'var(--color-success-bg)',
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
        <span className="t-eyebrow">Needs Attention</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {visibleItems.map((item, idx) => (
          <div
            key={item.id}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              // The list is priority-ordered; the top item is the one recommended
              // action, so it alone gets weight (border + shadow + a little air).
              padding: idx === 0 ? '16px 18px' : '12px 16px',
              borderRadius: 'var(--radius-card)',
              background: item.bg,
              border: idx === 0 ? `2px solid ${item.border}` : `1px solid ${item.border}`,
              boxShadow: idx === 0 ? 'var(--shadow-card)' : 'none',
              gap: 12,
              position: 'relative',
            }}
          >
            {idx === 0 && visibleItems.length > 1 && (
              <span style={{
                position: 'absolute', top: -9, left: 14,
                padding: '1px 9px', borderRadius: 'var(--radius-pill)',
                background: item.color, color: 'white',
                fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em',
              }}>
                Do this first
              </span>
            )}
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
        {overflow > 0 && (
          <Link
            href="/pipeline"
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 4, alignSelf: 'flex-start',
              fontSize: 13, fontWeight: 500, color: 'var(--color-accent)',
              textDecoration: 'none', padding: '2px 0',
            }}
          >
            +{overflow} more to review <ArrowRight size={13} strokeWidth={1.5} />
          </Link>
        )}
      </div>
    </div>
  )
}

function fmtMoney(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000)     return `$${(n / 1_000).toFixed(0)}k`
  return `$${n.toFixed(0)}`
}
