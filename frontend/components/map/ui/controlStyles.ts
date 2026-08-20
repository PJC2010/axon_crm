import type { CSSProperties } from 'react'

/**
 * Pill style for the map's overlay toggles and the mode switch.
 *
 * Shared rather than duplicated per control because the active state is the
 * thing that has to stay consistent: an inverted pill (ink background, paper
 * text) is how this map says "on", and three controls each deciding that
 * independently is how they drift apart.
 */
export function overlayBtn(active: boolean, touch = false): CSSProperties {
  return {
    display: 'flex', alignItems: 'center', gap: 5,
    // A fixed 6px vertical padding put every overlay toggle well under the 44px
    // touch target the ZIP picker's own rows already use. `touch` opts a control
    // into a thumb-sized version without changing its desktop density.
    padding: touch ? '11px 14px' : '6px 12px',
    minHeight: touch ? 44 : undefined,
    fontSize: 12, fontWeight: 500, borderRadius: 'var(--radius-pill)', cursor: 'pointer',
    border: '1px solid var(--color-ink-200)',
    background: active ? 'var(--color-ink-900)' : 'var(--color-paper)',
    color: active ? 'var(--color-paper)' : 'var(--color-ink-700)',
  }
}

/**
 * Pill style for the map's text inputs and selects.
 *
 * Was inlined verbatim at four call sites in the header — the vertical filter,
 * the status filter, the signal-window picker and the heatmap metric — which is
 * how three of them ended up at 12px while the ZIP picker had already learned
 * that anything under 16px makes iOS zoom the page on focus. `touch` opts into
 * the size that doesn't.
 */
export function fieldStyle(touch = false): CSSProperties {
  return {
    padding: touch ? '9px 12px' : '6px 10px',
    minHeight: touch ? 44 : undefined,
    fontSize: touch ? 16 : 12,
    borderRadius: 'var(--radius-pill)',
    border: '1px solid var(--color-ink-200)',
    background: 'var(--color-paper)',
    color: 'var(--color-ink-900)',
  }
}
