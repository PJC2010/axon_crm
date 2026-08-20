import type { CSSProperties } from 'react'

/**
 * Pill style for the map's overlay toggles and the mode switch.
 *
 * Shared rather than duplicated per control because the active state is the
 * thing that has to stay consistent: an inverted pill (ink background, paper
 * text) is how this map says "on", and three controls each deciding that
 * independently is how they drift apart.
 */
export function overlayBtn(active: boolean): CSSProperties {
  return {
    display: 'flex', alignItems: 'center', gap: 5, padding: '6px 12px',
    fontSize: 12, fontWeight: 500, borderRadius: 'var(--radius-pill)', cursor: 'pointer',
    border: '1px solid var(--color-ink-200)',
    background: active ? 'var(--color-ink-900)' : 'var(--color-paper)',
    color: active ? 'var(--color-paper)' : 'var(--color-ink-700)',
  }
}
