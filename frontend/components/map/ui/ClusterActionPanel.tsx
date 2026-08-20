'use client'
import { Sparkles, X } from 'lucide-react'

/**
 * Floating panel shown when a customer-cluster hull is clicked — fires the
 * "prospect this area" flow with the map's current vertical filter.
 *
 * `busy` is load-bearing: prospecting hits a paid provider and can take a while,
 * so the button must visibly disable rather than invite a second click that
 * spends money twice.
 */
export function ClusterActionPanel({
  cluster, busy, onProspect, onClose,
}: {
  cluster: { label: number; count: number }
  busy: boolean
  onProspect: () => void
  onClose: () => void
}) {
  return (
    <div style={{
      position: 'absolute', bottom: 16, left: '50%', transform: 'translateX(-50%)',
      background: 'var(--color-paper)', border: '1px solid var(--color-ink-200)',
      borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)',
      padding: '12px 14px', display: 'flex', alignItems: 'center', gap: 12, maxWidth: '92%',
      flexWrap: 'wrap', justifyContent: 'center',
      // Above the legend, which also sits at bottom:16. Neither declared a
      // z-index before, so stacking fell to DOM order and the legend was simply
      // obscured on a narrow screen. Phase 5's bottom sheet removes the overlap
      // properly; until then, at least make the winner deliberate.
      zIndex: 3,
    }}>
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-ink-900)' }}>
          Cluster #{cluster.label}
        </div>
        <div style={{ fontSize: 11, color: 'var(--color-ink-500)' }}>
          {cluster.count} active customer{cluster.count === 1 ? '' : 's'} here
        </div>
      </div>
      <button
        onClick={onProspect}
        disabled={busy}
        style={{
          display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px',
          fontSize: 12, fontWeight: 600, borderRadius: 'var(--radius-pill)', border: 'none',
          cursor: busy ? 'default' : 'pointer', opacity: busy ? 0.6 : 1,
          background: 'var(--color-accent)', color: '#ffffff',
        }}
      >
        <Sparkles size={13} strokeWidth={1.5} /> {busy ? 'Prospecting…' : 'Prospect this area'}
      </button>
      <button onClick={onClose} className="dash-icon-btn borderless" title="Close">
        <X size={15} strokeWidth={1.5} />
      </button>
    </div>
  )
}
