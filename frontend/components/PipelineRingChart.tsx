'use client'
import { useEffect, useState, useCallback } from 'react'
import { getPipelineStats } from '@/lib/api'

const STAGES: { key: string; label: string; color: string }[] = [
  { key: 'new',         label: 'New',        color: 'var(--color-ink-300)' },
  { key: 'contacted',   label: 'Contacted',  color: 'var(--color-ocean-d)' },
  { key: 'qualified',   label: 'Qualified',  color: 'var(--color-accent)' },
  { key: 'quote_sent',  label: 'Quote Sent', color: 'var(--color-gold)' },
  { key: 'won',         label: 'Won',        color: 'var(--color-moss)' },
]

export function PipelineRingChart() {
  const [stats, setStats] = useState<Record<string, { count: number; total_value: number }> | null>(null)
  const [loading, setLoading] = useState(true)
  const [hovered, setHovered] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try { setStats(await getPipelineStats()) }
    catch { /* silently fail */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) {
    return <div style={{ height: 200, borderRadius: 'var(--radius-card)', background: 'var(--color-surface)', boxShadow: 'var(--shadow-card)', opacity: 0.5 }} />
  }
  if (!stats) return null

  const segments = STAGES.map(s => ({
    ...s,
    count: stats[s.key]?.count ?? 0,
    value: stats[s.key]?.total_value ?? 0,
  })).filter(s => s.count > 0)

  const total = segments.reduce((s, seg) => s + seg.count, 0)
  if (total === 0) return null

  const cx = 50, cy = 50, r = 36, strokeWidth = 10
  const circumference = 2 * Math.PI * r
  let offset = 0

  return (
    <div style={{
      background: 'var(--color-surface)', borderRadius: 'var(--radius-card)',
      boxShadow: 'var(--shadow-card)', padding: '16px 18px',
    }}>
      <span className="t-eyebrow" style={{ display: 'block', marginBottom: 12 }}>Pipeline Distribution</span>

      <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
        <div style={{ position: 'relative', width: 120, height: 120, flexShrink: 0 }}>
          <svg viewBox="0 0 100 100" style={{ width: '100%', height: '100%', transform: 'rotate(-90deg)' }}>
            {segments.map(seg => {
              const pct = seg.count / total
              const dashLen = pct * circumference
              const gap = circumference - dashLen
              const thisOffset = offset
              offset += dashLen
              const isHovered = hovered === seg.key
              return (
                <circle
                  key={seg.key}
                  cx={cx} cy={cy} r={r}
                  fill="none"
                  stroke={seg.color}
                  strokeWidth={isHovered ? strokeWidth + 3 : strokeWidth}
                  strokeDasharray={`${dashLen} ${gap}`}
                  strokeDashoffset={-thisOffset}
                  strokeLinecap="butt"
                  onMouseEnter={() => setHovered(seg.key)}
                  onMouseLeave={() => setHovered(null)}
                  style={{ cursor: 'pointer', transition: 'stroke-width 0.2s ease', opacity: hovered && !isHovered ? 0.5 : 1 }}
                />
              )
            })}
          </svg>
          <div style={{
            position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center', pointerEvents: 'none',
          }}>
            <span style={{ fontSize: 22, fontWeight: 700, fontFamily: 'var(--font-display)', color: 'var(--color-ink-900)', lineHeight: 1 }}>
              {total}
            </span>
            <span style={{ fontSize: 10, color: 'var(--color-ink-400)', marginTop: 2 }}>leads</span>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: 1, minWidth: 0 }}>
          {segments.map(seg => {
            const pct = Math.round((seg.count / total) * 100)
            const isHovered = hovered === seg.key
            return (
              <div
                key={seg.key}
                style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  padding: '3px 6px', borderRadius: 'var(--radius-button)',
                  background: isHovered ? 'var(--color-paper)' : 'transparent',
                  transition: 'background 0.15s ease',
                  cursor: 'pointer',
                }}
                onMouseEnter={() => setHovered(seg.key)}
                onMouseLeave={() => setHovered(null)}
              >
                <div style={{ width: 8, height: 8, borderRadius: '50%', background: seg.color, flexShrink: 0 }} />
                <span style={{ fontSize: 12, color: 'var(--color-ink-700)', flex: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {seg.label}
                </span>
                <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-ink-900)', fontFamily: 'var(--font-mono)' }}>
                  {seg.count}
                </span>
                <span style={{ fontSize: 10, color: 'var(--color-ink-400)', minWidth: 28, textAlign: 'right' }}>
                  {pct}%
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
