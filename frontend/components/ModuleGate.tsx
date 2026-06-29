'use client'
import Link from 'next/link'
import { Lock } from 'lucide-react'
import { useEntitlements } from '@/hooks/useEntitlements'
import type { ModuleKey } from '@/lib/types'

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
