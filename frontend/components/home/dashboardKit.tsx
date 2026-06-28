'use client'
/* ── Home dashboard kit ──
   Charting + interaction primitives for the redesigned Home dashboard
   (Axon Design System · "Clarity" direction). Ported from the design-system
   `prototypes/dashboard-redesign` helpers into typed, product-ready React.
   All visual values come from design-system CSS variables. */
import { useEffect, useId, useRef, useState } from 'react'
import { ArrowUpRight, X } from 'lucide-react'

export const MONTH_ABBR = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

/* Tasteful count-up for hero numbers only. Honors prefers-reduced-motion. */
export function useCountUp(target: number, duration = 1100): number {
  const [val, setVal] = useState(0)
  const raf = useRef(0)
  useEffect(() => {
    if (!Number.isFinite(target)) { setVal(0); return }
    const reduce = typeof window !== 'undefined'
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduce) { setVal(target); return }
    const t0 = performance.now()
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / duration)
      const e = 1 - Math.pow(1 - p, 3)
      setVal(target * e)
      if (p < 1) raf.current = requestAnimationFrame(tick)
      else setVal(target)
    }
    raf.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf.current)
  }, [target, duration])
  return val
}

/* Area + line sparkline drawn from a number[]. */
export function Sparkline({
  data, w = 120, h = 36, color = 'var(--color-accent-300)', fill = true, strokeWidth = 1.6,
}: {
  data: number[]; w?: number; h?: number; color?: string; fill?: boolean; strokeWidth?: number
}) {
  const gid = 'sg-' + useId().replace(/:/g, '')
  if (!data || data.length < 2) return null
  const min = Math.min(...data), max = Math.max(...data)
  const span = max - min || 1
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w
    const y = h - ((v - min) / span) * (h - 4) - 2
    return [x, y] as const
  })
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ')
  const area = `${line} L${w},${h} L0,${h} Z`
  const last = pts[pts.length - 1]
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: 'block', overflow: 'visible' }} aria-hidden="true">
      {fill && (
        <>
          <defs>
            <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.22" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={area} fill={`url(#${gid})`} />
        </>
      )}
      <path d={line} fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={last[0]} cy={last[1]} r="2.4" fill={color} />
    </svg>
  )
}

/* Grouped bar chart: money in (revenue) vs out (expenses) by month. */
export interface CashflowDatum { m: string; inv: number; out: number }
export function CashflowBars({ data, h = 140 }: { data: CashflowDatum[]; h?: number }) {
  const max = Math.max(...data.flatMap(d => [d.inv, d.out]), 1)
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 14, height: h, paddingTop: 6 }}>
      {data.map((d) => (
        <div key={d.m} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, height: '100%' }}>
          <div style={{ flex: 1, display: 'flex', alignItems: 'flex-end', gap: 3, width: '100%', justifyContent: 'center' }}>
            <div title={`In ${d.inv.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })}`}
              style={{ width: 11, height: `${(d.inv / max) * 100}%`, minHeight: 2, background: 'var(--color-accent)', borderRadius: '2px 2px 0 0' }} />
            <div title={`Out ${d.out.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })}`}
              style={{ width: 11, height: `${(d.out / max) * 100}%`, minHeight: 2, background: 'var(--color-ink-200)', borderRadius: '2px 2px 0 0' }} />
          </div>
          <span style={{ fontSize: 10, color: 'var(--color-ink-400)' }}>{d.m}</span>
        </div>
      ))}
    </div>
  )
}

/* ── KPI tile: icon + eyebrow, big tabular value, comparison context, optional
   sparkline. Lifts on hover and opens a drill-down drawer. ── */
export type ContextTone = 'moss' | 'danger' | 'muted'
export interface KpiTileProps {
  icon: React.ReactNode
  label: string
  value: string
  context?: React.ReactNode
  contextTone?: ContextTone
  spark?: number[]
  sparkColor?: string
  onOpen?: () => void
}
export function KpiTile({ icon, label, value, context, contextTone = 'muted', spark, sparkColor, onOpen }: KpiTileProps) {
  const [hover, setHover] = useState(false)
  const ctxColor = contextTone === 'danger' ? 'var(--color-danger)'
    : contextTone === 'moss' ? 'var(--color-moss)' : 'var(--color-ink-400)'
  return (
    <button
      onClick={onOpen}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        textAlign: 'left', cursor: onOpen ? 'pointer' : 'default', position: 'relative', overflow: 'hidden',
        background: 'var(--color-surface)', borderRadius: 'var(--radius-card)',
        boxShadow: 'var(--shadow-card)', border: '1px solid transparent',
        padding: '15px 16px', minHeight: 116, width: '100%',
        transform: hover ? 'translateY(-2px)' : 'none',
        borderColor: hover ? 'var(--color-ink-200)' : 'transparent',
        transition: 'transform 140ms cubic-bezier(0.4,1,0.75,0.9), border-color 140ms',
        fontFamily: 'var(--font-sans)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 }}>
        {icon}
        <span className="t-eyebrow">{label}</span>
        {onOpen && (
          <ArrowUpRight size={13} strokeWidth={1.5} color="var(--color-ink-300)"
            style={{ marginLeft: 'auto', opacity: hover ? 1 : 0, transition: 'opacity 120ms' }} />
        )}
      </div>
      <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 8 }}>
        <div>
          <p className="tabular" style={{ margin: '0 0 5px', fontSize: 25, fontWeight: 700, color: 'var(--color-ink-900)', lineHeight: 1 }}>{value}</p>
          {context != null && <span style={{ fontSize: 11.5, fontWeight: 600, color: ctxColor }}>{context}</span>}
        </div>
        {spark && spark.length >= 2 && <Sparkline data={spark} w={66} h={32} color={sparkColor || 'var(--color-accent-300)'} />}
      </div>
    </button>
  )
}

/* ── Right-side drill-down drawer (progressive disclosure) ── */
export interface DrawerRow { label: string; value: string; tone?: ContextTone }
export function DrillDrawer({
  open, onClose, eyebrow, title, rows, note, cta, children,
}: {
  open: boolean
  onClose: () => void
  eyebrow?: string
  title?: string
  rows?: DrawerRow[]
  note?: string
  cta?: { label: string; href: string }
  children?: React.ReactNode
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  return (
    <>
      <div
        onClick={onClose}
        aria-hidden="true"
        style={{
          position: 'fixed', inset: 0, zIndex: 40,
          background: 'rgba(17,20,24,0.55)', backdropFilter: 'blur(2px)',
          opacity: open ? 1 : 0, pointerEvents: open ? 'auto' : 'none',
          transition: 'opacity 180ms cubic-bezier(0.4,1,0.75,0.9)',
        }}
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={title}
        style={{
          position: 'fixed', top: 0, right: 0, bottom: 0, width: 'min(440px, 92vw)', zIndex: 41,
          background: 'var(--color-paper)', borderLeft: '1px solid var(--color-ink-200)',
          boxShadow: 'var(--shadow-drawer)',
          transform: open ? 'translateX(0)' : 'translateX(100%)',
          transition: 'transform 220ms cubic-bezier(0.4,1,0.75,0.9)',
          display: 'flex', flexDirection: 'column',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', padding: '20px 22px 16px', borderBottom: '1px solid var(--color-ink-100)' }}>
          <div>
            {eyebrow && <p className="t-eyebrow" style={{ margin: '0 0 4px' }}>{eyebrow}</p>}
            <h3 style={{ margin: 0, fontFamily: 'var(--font-display)', fontSize: 19, fontWeight: 600, color: 'var(--color-ink-900)' }}>{title}</h3>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            style={{ background: 'transparent', border: '1px solid var(--color-ink-200)', borderRadius: 'var(--radius-button)', width: 30, height: 30, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', color: 'var(--color-ink-500)' }}
          >
            <X size={15} strokeWidth={1.5} />
          </button>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '18px 22px 28px' }}>
          {rows && rows.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 1, marginBottom: 18 }}>
              {rows.map((r, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '11px 0', borderBottom: '1px solid var(--color-ink-100)' }}>
                  <span style={{ fontSize: 13.5, color: 'var(--color-ink-600)' }}>{r.label}</span>
                  <span className="tabular" style={{ fontSize: 13.5, fontWeight: 600, color: r.tone === 'danger' ? 'var(--color-danger)' : r.tone === 'moss' ? 'var(--color-moss)' : 'var(--color-ink-900)' }}>{r.value}</span>
                </div>
              ))}
            </div>
          )}
          {children}
          {cta && (
            <a
              href={cta.href}
              style={{
                display: 'block', textAlign: 'center', width: '100%', padding: '11px 0',
                borderRadius: 'var(--radius-button)', border: 'none', background: 'var(--color-accent)',
                color: 'var(--color-cream)', fontSize: 13.5, fontWeight: 600, cursor: 'pointer',
                fontFamily: 'var(--font-sans)', textDecoration: 'none',
              }}
            >
              {cta.label}
            </a>
          )}
          {note && <p style={{ margin: '14px 0 0', fontSize: 11.5, color: 'var(--color-ink-400)', textAlign: 'center' }}>{note}</p>}
        </div>
      </aside>
    </>
  )
}
