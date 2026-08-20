'use client'
import { Layers } from 'lucide-react'

/**
 * Says out loud that the map is showing a slice.
 *
 * `/api/map/properties` caps at 2,000 rows and orders by `lead_score DESC NULLS
 * LAST`. The frontend never sent a limit, so a dense viewport quietly rendered
 * the top-scoring 2,000 and looked complete. A rep panning a busy ZIP had no way
 * to know the map was lying to them by omission.
 *
 * The ordering detail matters and is why the copy isn't just "showing 2,000":
 * truncation drops the *lowest*-scored leads first, which is a sensible bias
 * when you're prospecting and an actively misleading one when you've filtered to
 * `lost` or `not_interested` and are looking at what you think is all of them.
 */
export function TruncationNotice({ limit, isMobile }: { limit: number; isMobile: boolean }) {
  return (
    <div
      role="status"
      style={{
        position: 'absolute',
        top: isMobile ? 44 : 10,
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 3,
        display: 'flex', alignItems: 'center', gap: 6,
        maxWidth: '92%',
        padding: '5px 12px',
        background: 'var(--color-gold-soft)',
        border: '1px solid var(--color-gold)',
        borderRadius: 'var(--radius-pill)',
        boxShadow: 'var(--shadow-card)',
        color: 'var(--color-gold)',
        fontSize: 11, fontWeight: 500, lineHeight: 1.4,
        pointerEvents: 'none',
        textAlign: 'center',
      }}
    >
      <Layers size={12} strokeWidth={1.5} style={{ flexShrink: 0 }} />
      <span>
        Showing the {limit.toLocaleString()} highest-scoring here — zoom in to see the rest
      </span>
    </div>
  )
}
