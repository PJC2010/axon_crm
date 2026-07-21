'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { CheckCircle2, FileText } from 'lucide-react'
import { useCountUp } from './home/dashboardKit'
import { useEntitlements } from '@/hooks/useEntitlements'

/**
 * The won-deal moment (UX audit: emotional design / peak-end). A brief
 * accent-colored toast with the job value counting up and the one next step
 * ("Create invoice"). No confetti; useCountUp already honors
 * prefers-reduced-motion. Auto-dismisses after ~4s so the peak stays a peak.
 */
export interface WonDeal {
  /** Job value in dollars; null renders the message without a count-up. */
  value: number | null
  /** Short label for what was won (address / customer name). */
  label?: string | null
}

const AUTO_DISMISS_MS = 4000

export function WonCelebration({ deal, onDone }: { deal: WonDeal; onDone: () => void }) {
  const { hasModule } = useEntitlements()
  const [visible, setVisible] = useState(false)
  const animated = useCountUp(deal.value ?? 0, 900)

  useEffect(() => {
    const show = requestAnimationFrame(() => setVisible(true))
    const hide = setTimeout(() => {
      setVisible(false)
      setTimeout(onDone, 250)
    }, AUTO_DISMISS_MS)
    return () => { cancelAnimationFrame(show); clearTimeout(hide) }
  }, [onDone])

  const money = deal.value != null && deal.value > 0
    ? `$${Math.round(animated).toLocaleString('en-US')}`
    : null

  return (
    <div
      role="status"
      style={{
        position: 'fixed', bottom: 24, left: '50%', zIndex: 400,
        transform: visible ? 'translate(-50%, 0)' : 'translate(-50%, 12px)',
        opacity: visible ? 1 : 0,
        transition: 'opacity 220ms, transform 220ms',
        display: 'flex', alignItems: 'center', gap: 12,
        padding: '14px 18px',
        maxWidth: 'min(92vw, 420px)',
        background: 'var(--color-accent)',
        color: 'white',
        borderRadius: 'var(--radius-card)',
        boxShadow: 'var(--shadow-modal)',
      }}
    >
      <CheckCircle2 size={22} strokeWidth={2} style={{ flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{ margin: 0, fontSize: 14.5, fontWeight: 700, lineHeight: 1.3 }}>
          🎉 {money ? `${money} job won — nice work` : 'Job won — nice work'}
        </p>
        {deal.label && (
          <p style={{ margin: '2px 0 0', fontSize: 12, opacity: 0.85, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {deal.label}
          </p>
        )}
      </div>
      {hasModule('invoicing') && (
        <Link
          href="/bookkeeping"
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '0 14px', minHeight: 44,
            borderRadius: 'var(--radius-pill)',
            background: 'rgba(255,255,255,0.18)', color: 'white',
            fontSize: 12.5, fontWeight: 600, textDecoration: 'none',
            whiteSpace: 'nowrap', flexShrink: 0,
          }}
        >
          <FileText size={13} strokeWidth={2} /> Create invoice
        </Link>
      )}
    </div>
  )
}
