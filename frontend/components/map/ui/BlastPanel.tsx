'use client'
import { X, Footprints } from 'lucide-react'
import { GRADE_TOKENS, type Grade } from '@/lib/gradeColors'
import { formatDistance } from '../draw'
import type { NeighborHit } from '@/lib/types'

/**
 * The door-knock list around a completed job.
 *
 * A ranked list beside the ring rather than only pins on the map, because the
 * output of this question is a route: a rep works down it in order, and reading
 * order off a scatter of dots is exactly the thing a list is better at. The
 * order is the server's — nearest, then best-scoring — and neither side re-sorts,
 * so a row and its pin always mean the same thing.
 */
export function BlastPanel({
  address, hits, radiusM, onPick, onClose,
}: {
  address: string
  hits: NeighborHit[]
  radiusM: number
  onPick: (id: number) => void
  onClose: () => void
}) {
  return (
    <div style={{
      position: 'absolute', bottom: 16, left: '50%', transform: 'translateX(-50%)',
      background: 'var(--color-paper)', border: '1px solid var(--color-ink-200)',
      borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)',
      padding: '12px 14px', maxWidth: '92%', width: 320, zIndex: 3,
      display: 'flex', flexDirection: 'column', gap: 8,
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: 13, fontWeight: 600, color: 'var(--color-ink-900)',
            display: 'flex', alignItems: 'center', gap: 6,
          }}>
            <Footprints size={13} strokeWidth={1.5} /> Neighbors to knock
          </div>
          <div style={{
            fontSize: 11, color: 'var(--color-ink-500)', marginTop: 2,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {hits.length} open within {formatDistance(radiusM)} of {address || 'this job'}
          </div>
        </div>
        <button onClick={onClose} className="dash-icon-btn borderless" title="Clear">
          <X size={15} strokeWidth={1.5} />
        </button>
      </div>

      <div style={{ maxHeight: 168, overflowY: 'auto', margin: '0 -4px' }}>
        {hits.map((h, i) => {
          const g = (h.score_grade ?? '') as Grade
          const token = GRADE_TOKENS[g]
          return (
            <button
              key={h.id}
              onClick={() => onPick(h.id)}
              style={{
                display: 'flex', alignItems: 'center', gap: 8, width: '100%',
                // 44px: this is a list a rep taps while standing on a driveway.
                minHeight: 44, padding: '6px 4px', border: 'none', background: 'transparent',
                cursor: 'pointer', textAlign: 'left', color: 'var(--color-ink-700)',
              }}
            >
              <span className="tabular" style={{
                width: 18, flexShrink: 0, fontSize: 11, color: 'var(--color-ink-400)',
              }}>{i + 1}</span>
              <span style={{
                flex: 1, minWidth: 0, fontSize: 12,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {h.address || 'No address on file'}
              </span>
              {token && (
                <span style={{
                  fontSize: 10, fontWeight: 600, padding: '1px 6px',
                  borderRadius: 'var(--radius-pill)', background: token.bg, color: token.fg,
                }}>{g}</span>
              )}
              <span className="tabular" style={{
                fontSize: 11, color: 'var(--color-ink-500)', flexShrink: 0, width: 52,
                textAlign: 'right',
              }}>
                {formatDistance(h.distance_m)}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

/**
 * The offer, rendered inside the drawer for a won job.
 *
 * Gated on `won` rather than offered everywhere because the endpoint's own
 * semantics are "around a *completed* job" — it excludes won/lost/converted
 * leads from its results, so asking it about an open lead returns that lead's
 * competitors, not a follow-on route.
 *
 * It lives in the drawer rather than floating over the map because the drawer is
 * full-width on a phone: a map-level panel would be behind it, unreachable on
 * exactly the device a rep is holding on the driveway.
 */
export function NeighborsPrompt({
  busy, onShow,
}: {
  busy: boolean
  onShow: () => void
}) {
  return (
    <button
      onClick={onShow}
      disabled={busy}
      style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
        width: '100%', padding: '10px 14px', minHeight: 44,
        fontSize: 12, fontWeight: 600, borderRadius: 'var(--radius-pill)',
        border: '1px solid var(--color-accent)',
        cursor: busy ? 'default' : 'pointer', opacity: busy ? 0.6 : 1,
        background: 'transparent', color: 'var(--color-accent-300)',
      }}
    >
      <Footprints size={14} strokeWidth={1.5} />
      {busy ? 'Finding neighbors…' : 'Show neighbors to knock'}
    </button>
  )
}
