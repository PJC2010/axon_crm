'use client'
import { useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { ToastStack, useToast } from '@/components/Toast'
import { OpsBacklog } from './ops/OpsBacklog'
import { OpsJobs } from './ops/OpsJobs'
import { OpsRuns } from './ops/OpsRuns'
import { OpsSystem } from './ops/OpsSystem'

/* Platform operations: what the scheduler is doing, what every org's pipeline
   is doing, what is backing up, and which build is serving. Each section
   fetches on its own so a slow one never blanks the rest; the one Refresh
   re-reads them all. */

export function AdminOps() {
  const [refreshKey, setRefreshKey] = useState(0)
  const { toasts, show, dismiss } = useToast()

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
        <h2 className="t-eyebrow" style={{ margin: 0 }}>Operations</h2>
        <span style={{ fontSize: 12.5, color: 'var(--color-ink-500)' }}>
          Scheduler jobs, every org&apos;s pipeline runs, queues, and the build that is serving. Nothing here refreshes on its own.
        </span>
        <button
          className="btn-secondary"
          style={{ marginLeft: 'auto', fontSize: 12.5, padding: '4px 10px', display: 'inline-flex', alignItems: 'center', gap: 5 }}
          onClick={() => setRefreshKey((k) => k + 1)}
        >
          <RefreshCw size={12} strokeWidth={1.5} /> Refresh
        </button>
      </div>

      <OpsBacklog refreshKey={refreshKey} />
      <OpsJobs refreshKey={refreshKey} />
      <OpsRuns refreshKey={refreshKey} onToast={show} />
      <OpsSystem refreshKey={refreshKey} />
      <ToastStack toasts={toasts} onDismiss={dismiss} />
    </div>
  )
}
