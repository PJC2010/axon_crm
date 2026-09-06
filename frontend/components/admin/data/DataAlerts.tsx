'use client'
import { AlertTriangle } from 'lucide-react'
import type { DataHealthAlert } from '@/lib/types'

const COLOR: Record<DataHealthAlert['severity'], string> = {
  error: 'var(--color-danger)',
  warn: 'var(--color-warning)',
  info: 'var(--color-ink-400)',
}

/** Same card shape as the Overview's config-check list. */
export function DataAlerts({ alerts }: { alerts: DataHealthAlert[] }) {
  return (
    <>
      <h2 className="t-eyebrow" style={{ margin: '0 0 10px' }}>Needs attention</h2>
      <div style={{ background: 'var(--color-surface)', borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)', padding: '6px 16px', marginBottom: 26 }}>
        {alerts.length === 0 && (
          <p style={{ margin: 0, padding: '10px 0', fontSize: 13, color: 'var(--color-ink-500)' }}>Nothing looks out of place.</p>
        )}
        {alerts.map((a) => (
          <div key={a.key} style={{ display: 'flex', alignItems: 'flex-start', gap: 10, padding: '10px 0', borderBottom: '1px solid var(--color-ink-100)' }}>
            <AlertTriangle size={14} strokeWidth={1.75} color={COLOR[a.severity]} style={{ flexShrink: 0, marginTop: 2 }} />
            <div>
              <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-ink-900)' }}>{a.label}</span>
              <p style={{ margin: '2px 0 0', fontSize: 12.5, color: 'var(--color-ink-500)', lineHeight: 1.5 }}>{a.detail}</p>
            </div>
          </div>
        ))}
      </div>
    </>
  )
}
