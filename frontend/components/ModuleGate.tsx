'use client'
import Link from 'next/link'
import { Lock, Zap } from 'lucide-react'
import { useEntitlements } from '@/hooks/useEntitlements'
import type { ModuleKey, ScoringQuota } from '@/lib/types'

/**
 * Page/section guard for a feature module. Renders children when the account has
 * the module enabled, otherwise an "Upgrade to unlock" panel. The backend guards
 * are the real enforcement; this is the UX layer so locked features degrade
 * gracefully instead of erroring.
 */
export function ModuleGate({
  module,
  feature,
  children,
}: {
  module: ModuleKey
  feature?: string
  children: React.ReactNode
}) {
  const { hasModule, loading } = useEntitlements()

  // Avoid flashing locked content before entitlements resolve.
  if (loading) return null
  if (hasModule(module)) return <>{children}</>

  return <UpgradePanel feature={feature ?? module} />
}

/**
 * Inline meter for the monthly scored-lead allowance on metered plans
 * ("18 of 25 scored leads used — upgrade for unlimited"). Renders nothing on
 * unlimited plans or before the quota state loads. Pass `quota` when the page
 * already has fresher state (e.g. the lead list response); otherwise the
 * account-features payload from useEntitlements is used.
 */
export function ScoringQuotaBanner({ quota }: { quota?: ScoringQuota | null }) {
  const { scoringQuota } = useEntitlements()
  const q = quota ?? scoringQuota
  if (!q) return null

  const exhausted = q.remaining <= 0
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
      padding: '8px 16px', fontSize: 12.5,
      background: exhausted ? 'var(--color-warning-bg)' : 'var(--color-surface)',
      borderBottom: '1px solid var(--color-ink-200)',
      color: 'var(--color-ink-700)',
    }}>
      <Zap size={13} strokeWidth={1.5} style={{ color: exhausted ? 'var(--color-gold)' : 'var(--color-accent)', flexShrink: 0 }} />
      <span>
        <b>{q.used} of {q.limit}</b> scored leads used this month
        {exhausted && ' — new scored leads show masked until next month'}
      </span>
      <Link
        href="/settings"
        style={{ fontWeight: 600, color: 'var(--color-accent)', textDecoration: 'none' }}
      >
        Upgrade for unlimited →
      </Link>
    </div>
  )
}

function UpgradePanel({ feature }: { feature: string }) {
  return (
    <div style={{
      minHeight: '60vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
    }}>
      <div style={{
        maxWidth: 420, textAlign: 'center',
        background: 'var(--color-surface)',
        border: '1px solid var(--color-ink-200)',
        borderRadius: 'var(--radius-card, 12px)',
        boxShadow: 'var(--shadow-pop)',
        padding: '32px 28px',
      }}>
        <div style={{
          width: 48, height: 48, margin: '0 auto 16px', borderRadius: 12,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: 'var(--color-ink-100, rgba(0,0,0,0.05))',
        }}>
          <Lock size={22} strokeWidth={1.5} color="var(--color-ink-500)" />
        </div>
        <h2 style={{ fontSize: 18, fontWeight: 600, margin: '0 0 8px', color: 'var(--color-ink-900)' }}>
          {feature} isn’t on your plan
        </h2>
        <p style={{ fontSize: 14, lineHeight: 1.5, color: 'var(--color-ink-500)', margin: '0 0 20px' }}>
          This feature is available on a higher plan. Contact your account owner to
          enable it.
        </p>
        <Link
          href="/home"
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '10px 16px', borderRadius: 'var(--radius-button)',
            background: 'var(--color-accent)', color: 'var(--color-ink-900)',
            textDecoration: 'none', fontSize: 14, fontWeight: 600,
          }}
        >
          Back to Home
        </Link>
      </div>
    </div>
  )
}
