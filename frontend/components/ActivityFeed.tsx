'use client'
import { useEffect, useState, useCallback } from 'react'
import { Activity, FileText, CheckSquare, ArrowRight, DollarSign, UserPlus } from 'lucide-react'
import Link from 'next/link'
import { getLeads, getTasks, getInvoices } from '@/lib/api'
import type { Lead, Task, Invoice } from '@/lib/types'

interface FeedItem {
  id: string
  icon: React.ReactNode
  iconColor: string
  title: string
  detail: string
  time: string
  link?: string
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  if (days === 1) return 'yesterday'
  if (days < 7) return `${days}d ago`
  return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export function ActivityFeed() {
  const [items, setItems] = useState<FeedItem[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [leadsRes, tasksRes, invoicesRes] = await Promise.allSettled([
        getLeads({ sort: 'updated_at', page: 1, page_size: 8 }),
        getTasks({ }),
        getInvoices({ page: 1, page_size: 5 }),
      ])

      const feed: FeedItem[] = []

      if (leadsRes.status === 'fulfilled') {
        leadsRes.value.results.forEach((lead: Lead) => {
          if (!lead.updated_at) return
          feed.push({
            id: `lead-${lead.id}`,
            icon: <UserPlus size={13} strokeWidth={1.8} />,
            iconColor: 'var(--color-accent)',
            title: lead.owner_name ?? lead.address,
            detail: `Lead ${lead.status === 'new' ? 'added' : `moved to ${lead.status.replace('_', ' ')}`}`,
            time: lead.updated_at,
            link: '/dashboard',
          })
        })
      }

      if (tasksRes.status === 'fulfilled') {
        (tasksRes.value as Task[]).slice(0, 5).forEach((task: Task) => {
          feed.push({
            id: `task-${task.id}`,
            icon: <CheckSquare size={13} strokeWidth={1.8} />,
            iconColor: task.is_complete ? 'var(--color-moss)' : 'var(--color-gold)',
            title: task.title,
            detail: task.is_complete ? 'Completed' : task.due_date ? `Due ${new Date(task.due_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}` : 'No due date',
            time: task.updated_at ?? task.created_at,
            link: '/tasks',
          })
        })
      }

      if (invoicesRes.status === 'fulfilled') {
        invoicesRes.value.items.forEach((inv: Invoice) => {
          feed.push({
            id: `inv-${inv.id}`,
            icon: inv.status === 'paid' ? <DollarSign size={13} strokeWidth={1.8} /> : <FileText size={13} strokeWidth={1.8} />,
            iconColor: inv.status === 'paid' ? 'var(--color-moss)' : inv.status === 'overdue' ? 'var(--color-danger)' : 'var(--color-ink-500)',
            title: `Invoice #${inv.invoice_number}`,
            detail: `${inv.client_name} · $${inv.total.toLocaleString()} · ${inv.status}`,
            time: inv.created_at,
            link: '/bookkeeping',
          })
        })
      }

      feed.sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime())
      setItems(feed.slice(0, 8))
    } catch { /* silently fail */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) {
    return (
      <div style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <Activity size={14} strokeWidth={1.8} color="var(--color-ink-400)" />
          <span className="t-eyebrow">Recent Activity</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {[1,2,3].map(i => (
            <div key={i} style={{ height: 44, borderRadius: 'var(--radius-card)', background: 'white', boxShadow: 'var(--shadow-card)', opacity: 0.4 }} />
          ))}
        </div>
      </div>
    )
  }

  if (items.length === 0) return null

  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <Activity size={14} strokeWidth={1.8} color="var(--color-ink-400)" />
        <span className="t-eyebrow">Recent Activity</span>
      </div>

      <div style={{
        background: 'white', borderRadius: 'var(--radius-card)',
        boxShadow: 'var(--shadow-card)', overflow: 'hidden',
      }}>
        {items.map((item, idx) => (
          <div
            key={item.id}
            style={{
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '10px 14px',
              borderBottom: idx < items.length - 1 ? '1px solid var(--color-ink-100)' : 'none',
            }}
          >
            <div style={{
              width: 28, height: 28, borderRadius: '50%',
              background: `color-mix(in srgb, ${item.iconColor} 12%, transparent)`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexShrink: 0, color: item.iconColor,
            }}>
              {item.icon}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <p style={{
                margin: 0, fontSize: 13, fontWeight: 500, color: 'var(--color-ink-900)',
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {item.title}
              </p>
              <p style={{ margin: 0, fontSize: 11, color: 'var(--color-ink-400)' }}>
                {item.detail}
              </p>
            </div>
            <span style={{ fontSize: 10, color: 'var(--color-ink-400)', whiteSpace: 'nowrap', flexShrink: 0 }}>
              {timeAgo(item.time)}
            </span>
            {item.link && (
              <Link href={item.link} style={{ display: 'flex', color: 'var(--color-ink-300)' }}>
                <ArrowRight size={12} strokeWidth={1.5} />
              </Link>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
