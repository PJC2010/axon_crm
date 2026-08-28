'use client'
import React from 'react'

export interface SkeletonProps {
  /** Width — number is px, string passes through (e.g. '60%'). */
  w?: number | string
  /** Height in px. */
  h?: number
  radius?: number | string
  style?: React.CSSProperties
}

/**
 * One shimmering placeholder block. Compose these into the shape of the
 * content that is loading rather than showing a spinner or "Loading…" — the
 * layout then holds still when the real data arrives.
 */
export function Skeleton({ w = '100%', h = 12, radius, style }: SkeletonProps) {
  return (
    <span
      aria-hidden
      className="axon-skel"
      style={{
        display: 'block',
        width: typeof w === 'number' ? `${w}px` : w,
        height: h,
        borderRadius: radius ?? 'var(--radius-input)',
        ...style,
      }}
    />
  )
}

/**
 * A paragraph of skeleton lines. The last line is short, the way a real
 * ragged-right paragraph ends — a stack of equal-width bars reads as a
 * placeholder, not as text.
 */
export function SkeletonText({
  lines = 3,
  h = 11,
  gap = 8,
  style,
}: { lines?: number; h?: number; gap?: number; style?: React.CSSProperties }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap, ...style }}>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} h={h} w={i === lines - 1 ? '58%' : '100%'} />
      ))}
    </div>
  )
}

/**
 * Skeleton rows for a `<tbody>`. Renders real `<tr>`/`<td>` so the placeholder
 * inherits the table's own column widths — the bars land where the data will.
 * Column widths vary deterministically so the block doesn't read as a grid.
 */
export function SkeletonRows({
  rows = 6,
  cols,
  cellStyle,
}: { rows?: number; cols: number; cellStyle?: React.CSSProperties }) {
  const widths = ['70%', '45%', '85%', '35%', '60%', '50%', '75%', '40%']
  return (
    <>
      {Array.from({ length: rows }, (_, r) => (
        <tr key={r}>
          {Array.from({ length: cols }, (_, c) => (
            <td key={c} style={{ padding: '12px 10px', ...cellStyle }}>
              <Skeleton h={10} w={widths[(r + c * 3) % widths.length]} />
            </td>
          ))}
        </tr>
      ))}
    </>
  )
}

/** A stack of card-shaped placeholders, for card lists and dashboard grids. */
export function SkeletonCards({
  count = 3,
  h = 96,
  gap = 12,
  columns,
  style,
}: { count?: number; h?: number; gap?: number; columns?: number; style?: React.CSSProperties }) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: columns ? `repeat(${columns}, minmax(0, 1fr))` : '1fr',
        gap,
        ...style,
      }}
    >
      {Array.from({ length: count }, (_, i) => (
        <Skeleton key={i} h={h} radius="var(--radius-card)" />
      ))}
    </div>
  )
}

/**
 * Drop-in for the `Loading…` paragraph that stood in a card body: a short
 * title bar over a few text lines.
 */
export function SkeletonPanel({ lines = 3, style }: { lines?: number; style?: React.CSSProperties }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, ...style }}>
      <Skeleton h={13} w={140} />
      <SkeletonText lines={lines} />
    </div>
  )
}
