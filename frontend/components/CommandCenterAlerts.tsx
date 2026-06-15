'use client'
import { useEffect, useState } from 'react'
import { AlertTriangle, Clock, TrendingDown, ArrowRight } from 'lucide-react'
import Link from 'next/link'
import { getPipelineAlerts } from '@/lib/api'
import type { PipelineAlerts } from '@/lib/types'

const STATUS_LABELS: Record<string, string> = {
  new: 'New', contacted: 'Contacted', qualified: 'Qualified',
  quote_sent: 'Quote Sent', won: 'Won', lost: 'Lost', not_interested: 'Not Interested',
}

const MAX_VISIBLE = 5

function daysAgo(iso: string | null): number | null {
  if (!iso) return null
  const ms = Date.now() - new Date(iso).getTime()
  return Math.max(0, Math.floor(ms / 86_400_000))
}

export function CommandCenterAlerts() {
  const [alerts, setAlerts] = useState<PipelineAlerts | null>(null)

  useEffect(() => {
    getPipelineAlerts().then(setAlerts).catch(() => {})
  }, [])

  if (!alerts) return null
  const total =
    alerts.stuck_deals.count + alerts.overdue_followups.count + alerts.cooling_leads.count
  if (total === 0) return null

  return (
    <div style={{ marginBottom: 24 }}>
      <p className="t-eyebrow" style={{ margin: '0 0 10px' }}>Command Center</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

        {alerts.stuck_deals.count > 0 && (
          <AlertBucket
            icon={<AlertTriangle size={15} strokeWidth={1.5} color="var(--color-danger)" />}
            accent="var(--color-danger)"
            title="Stuck deals"
            count={alerts.stuck_deals.count}
            href="/pipeline"
          >
            {alerts.stuck_deals.items.slice(0, MAX_VISIBLE).map(d => (
              <Row
                key={d.id}
                primary={d.owner_name || d.address || d.contact_name || `Lead #${d.id}`}
                secondary={STATUS_LABELS[d.status] ?? d.status}
                meta={`${d.days_in_stage}d in stage`}
              />
            ))}
          </AlertBucket>
        )}

        {alerts.overdue_followups.count > 0 && (
          <AlertBucket
            icon={<Clock size={15} strokeWidth={1.5} color="var(--color-gold)" />}
            accent="var(--color-gold)"
            title="Overdue follow-ups"
            count={alerts.overdue_followups.count}
            href="/tasks"
          >
            {alerts.overdue_followups.items.slice(0, MAX_VISIBLE).map(t => (
              <Row
                key={t.id}
                primary={t.title}
                secondary={t.owner_name || t.address || '—'}
                meta={`${t.days_overdue}d overdue`}
              />
            ))}
          </AlertBucket>
        )}

        {alerts.cooling_leads.count > 0 && (
          <AlertBucket
            icon={<TrendingDown size={15} strokeWidth={1.5} color="var(--color-accent)" />}
            accent="var(--color-accent)"
            title="Cooling hot leads"
            count={alerts.cooling_leads.count}
            href="/dashboard"
          >
            {alerts.cooling_leads.items.slice(0, MAX_VISIBLE).map(l => {
              const idle = daysAgo(l.last_activity_at)
              return (
                <Row
                  key={l.id}
                  primary={l.owner_name || l.address || l.contact_name || `Lead #${l.id}`}
                  secondary={`Grade ${l.score_grade ?? '—'} · ${STATUS_LABELS[l.status] ?? l.status}`}
                  meta={idle != null ? `idle ${idle}d` : ''}
                />
              )
            })}
          </AlertBucket>
        )}
      </div>
    </div>
  )
}

function AlertBucket({ icon, accent, title, count, href, children }: {
  icon: React.ReactNode
  accent: string
  title: string
  count: number
  href: string
  children: React.ReactNode
}) {
  return (
    <div style={{
      background: 'white', borderRadius: 'var(--radius-card)',
      boxShadow: 'var(--shadow-card)', borderLeft: `4px solid ${accent}`, overflow: 'hidden',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 14px', borderBottom: '1px solid var(--color-ink-50)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {icon}
          <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-ink-900)' }}>{title}</span>
          <span style={{ padding: '1px 8px', borderRadius: 'var(--radius-pill)', background: 'var(--color-paper)', color: 'var(--color-ink-500)', fontSize: 12, fontWeight: 600 }}>{count}</span>
        </div>
        <Link href={href} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, color: accent, fontWeight: 500, textDecoration: 'none' }}>
          View <ArrowRight size={13} strokeWidth={1.5} />
        </Link>
      </div>
      <div>{children}</div>
    </div>
  )
}

function Row({ primary, secondary, meta }: { primary: string; secondary: string; meta: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 14px', borderBottom: '1px solid var(--color-ink-50)' }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{ margin: 0, fontSize: 13, fontWeight: 500, color: 'var(--color-ink-900)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{primary}</p>
        <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--color-ink-400)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{secondary}</p>
      </div>
      {meta && (
        <span className="tabular" style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-ink-500)', whiteSpace: 'nowrap', flexShrink: 0 }}>{meta}</span>
      )}
    </div>
  )
}
