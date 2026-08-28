'use client'
import { SkeletonCards } from '@/components/ds'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import {
  Activity, AlertTriangle, Building2, CreditCard, LogIn, Mail, Timer, Users, Webhook,
} from 'lucide-react'
import { adminSummary, adminSecurity } from '@/lib/api'
import type { AdminSummary, AdminSecurityReport, ConfigCheck } from '@/lib/types'
import { KpiTile } from '@/components/home/dashboardKit'
import { TH_STYLE, TD_STYLE, zebra, fmtDateTime } from './AdminTable'

const CHECK_COLOR: Record<ConfigCheck['status'], string> = {
  ok: 'var(--color-success)',
  warn: 'var(--color-warning)',
  error: 'var(--color-danger)',
  info: 'var(--color-ink-400)',
}

export function AdminOverview() {
  const [summary, setSummary] = useState<AdminSummary | null>(null)
  const [security, setSecurity] = useState<AdminSecurityReport | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // allSettled so one failing source doesn't blank the page (house pattern).
    Promise.allSettled([adminSummary(), adminSecurity()]).then(([s, sec]) => {
      if (s.status === 'fulfilled') setSummary(s.value)
      else setError('Failed to load platform summary')
      if (sec.status === 'fulfilled') setSecurity(sec.value)
    })
  }, [])

  if (error) return <p style={{ color: 'var(--color-danger)', fontSize: 13 }}>{error}</p>
  if (!summary) return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <SkeletonCards count={4} columns={4} h={88} gap={12} />
      <SkeletonCards count={2} columns={2} h={180} gap={12} />
    </div>
  )

  const icon = (I: typeof Users) => <I size={14} strokeWidth={1.5} color="var(--color-ink-400)" />
  const n = (v: number) => v.toLocaleString()

  const alerts = (security?.config_checks ?? []).filter((c) => c.status === 'error' || c.status === 'warn')
  const failed = security?.failed_by_ip ?? []

  return (
    <div>
      <h2 className="t-eyebrow" style={{ margin: '0 0 12px' }}>Platform</h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(215px, 1fr))', gap: 12, marginBottom: 26 }}>
        <KpiTile icon={icon(Building2)} label="Orgs" value={n(summary.accounts)}
          context={`+${summary.accounts_new_30d} in 30d`} contextTone={summary.accounts_new_30d > 0 ? 'moss' : 'muted'} />
        <KpiTile icon={icon(Users)} label="Users" value={n(summary.users_total)}
          context={`${n(summary.users_active)} active · ${n(summary.users_verified)} verified`} />
        <KpiTile icon={icon(Activity)} label="Active users · 7d" value={n(summary.active_users_7d)}
          context="logged in this week" />
        <KpiTile icon={icon(Timer)} label="Trials" value={n(summary.trials_active)}
          context={`${n(summary.trials_expired)} expired`} contextTone={summary.trials_expired > 0 ? 'danger' : 'muted'} />
        <KpiTile icon={icon(CreditCard)} label="Paying orgs" value={n(summary.paying)} />
        <KpiTile icon={icon(LogIn)} label="Logins · 24h" value={n(summary.logins_24h)}
          context={`${n(summary.failed_logins_24h)} failed`} contextTone={summary.failed_logins_24h > 0 ? 'danger' : 'muted'} />
        <KpiTile icon={icon(Activity)} label="Pipeline runs · 24h" value={n(summary.pipeline_runs_24h)}
          context={`${n(summary.pipeline_failures_7d)} failures in 7d`} contextTone={summary.pipeline_failures_7d > 0 ? 'danger' : 'muted'} />
        <KpiTile icon={icon(Webhook)} label="Webhook errors · 7d" value={n(summary.webhook_errors_7d)}
          contextTone={summary.webhook_errors_7d > 0 ? 'danger' : 'muted'} />
        <KpiTile icon={icon(Mail)} label="Prospect signups · 7d" value={n(summary.prospect_signups_7d)} />
      </div>

      {alerts.length > 0 && (
        <>
          <h2 className="t-eyebrow" style={{ margin: '0 0 10px' }}>Needs attention</h2>
          <div style={{ background: 'var(--color-surface)', borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)', padding: '6px 16px', marginBottom: 26 }}>
            {alerts.map((c) => (
              <div key={c.key} style={{ display: 'flex', alignItems: 'flex-start', gap: 10, padding: '10px 0', borderBottom: '1px solid var(--color-ink-100)' }}>
                <AlertTriangle size={14} strokeWidth={1.75} color={CHECK_COLOR[c.status]} style={{ flexShrink: 0, marginTop: 2 }} />
                <div>
                  <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-ink-900)' }}>{c.label}</span>
                  <p style={{ margin: '2px 0 0', fontSize: 12.5, color: 'var(--color-ink-500)', lineHeight: 1.5 }}>{c.detail}</p>
                </div>
              </div>
            ))}
            <div style={{ padding: '10px 0' }}>
              <Link href="/admin/security" style={{ fontSize: 12.5, color: 'var(--color-accent-300)', textDecoration: 'none' }}>
                All checks →
              </Link>
            </div>
          </div>
        </>
      )}

      <h2 className="t-eyebrow" style={{ margin: '0 0 10px' }}>Failed logins · 24h</h2>
      <div style={{ background: 'var(--color-surface)', borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)', overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={TH_STYLE}>IP</th>
              <th style={TH_STYLE}>Attempts</th>
              <th style={TH_STYLE}>Identifiers</th>
              <th style={TH_STYLE}>Last attempt</th>
            </tr>
          </thead>
          <tbody>
            {failed.length === 0 && (
              <tr><td colSpan={4} style={{ ...TD_STYLE, textAlign: 'center', padding: '28px 0', color: 'var(--color-ink-400)' }}>No failed logins in the last 24 hours</td></tr>
            )}
            {failed.map((r, i) => (
              <tr key={r.ip ?? i} style={{ background: zebra(i) }}>
                <td style={TD_STYLE} className="tabular">{r.ip ?? '—'}</td>
                <td style={TD_STYLE} className="tabular">{r.attempts}</td>
                <td style={TD_STYLE} className="tabular">{r.identifiers}</td>
                <td style={TD_STYLE}>{fmtDateTime(r.last_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
