'use client'
import Link from 'next/link'
import { ShieldCheck } from 'lucide-react'
import { NAV_ITEMS, isNavVisible } from '@/lib/nav'
import { useEntitlements } from '@/hooks/useEntitlements'
import { usePlatformAdmin } from '@/hooks/usePlatformAdmin'
import { useTerminology } from '@/hooks/useTerminology'

/**
 * Primary feature navigation, rendered from the central NAV_ITEMS config and
 * filtered by the account's enabled modules. Replaces the per-page hardcoded
 * link clusters so nav stays consistent and locked features simply don't appear.
 *
 * `current` omits the link to the page you're on; Settings/sign-out stay in each
 * header (they are always available and page-specific in placement).
 */
export function NavLinks({
  current,
  variant,
  onNavigate,
}: {
  current?: string
  variant: 'desktop' | 'mobile'
  onNavigate?: () => void
}) {
  const { hasModule } = useEntitlements()
  // Strict default (hidden while loading) — the Admin link must never flash
  // for a normal user. Like Settings, it lives outside NAV_ITEMS: it is
  // per-user (platform operators), not a module-gated tenant feature.
  const { isPlatformAdmin } = usePlatformAdmin()
  const { t } = useTerminology()
  const items = NAV_ITEMS.filter((it) => it.href !== current && isNavVisible(it, hasModule))
  const labelOf = (it: typeof NAV_ITEMS[number]) => (it.termKey ? t(it.termKey) : it.label)
  const showAdmin = isPlatformAdmin && current !== '/admin'

  if (variant === 'desktop') {
    return (
      <>
        {items.map((it) => {
          const Icon = it.icon
          return (
            <Link
              key={it.href}
              href={it.href}
              title={labelOf(it)}
              className="dash-icon-btn"
              style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '0 10px', textDecoration: 'none', color: 'inherit', fontSize: 13 }}
            >
              <Icon size={13} strokeWidth={1.5} />
              <span>{it.shortLabel ?? labelOf(it)}</span>
            </Link>
          )
        })}
        {showAdmin && (
          <Link
            href="/admin"
            title="Platform Admin"
            className="dash-icon-btn"
            style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '0 10px', textDecoration: 'none', color: 'inherit', fontSize: 13 }}
          >
            <ShieldCheck size={13} strokeWidth={1.5} />
            <span>Admin</span>
          </Link>
        )}
      </>
    )
  }

  return (
    <>
      {items.map((it) => {
        const Icon = it.icon
        return (
          <Link
            key={it.href}
            href={it.href}
            onClick={onNavigate}
            style={{
              display: 'flex', alignItems: 'center', gap: 12,
              padding: '12px 14px', minHeight: 48,
              borderRadius: 'var(--radius-button)',
              textDecoration: 'none', color: 'var(--color-ink-800)',
              fontSize: 15, fontWeight: 500,
            }}
          >
            <Icon size={18} strokeWidth={1.5} color="var(--color-ink-500)" />
            {labelOf(it)}
          </Link>
        )
      })}
      {showAdmin && (
        <Link
          href="/admin"
          onClick={onNavigate}
          style={{
            display: 'flex', alignItems: 'center', gap: 12,
            padding: '12px 14px', minHeight: 48,
            borderRadius: 'var(--radius-button)',
            textDecoration: 'none', color: 'var(--color-ink-800)',
            fontSize: 15, fontWeight: 500,
          }}
        >
          <ShieldCheck size={18} strokeWidth={1.5} color="var(--color-ink-500)" />
          Admin
        </Link>
      )}
    </>
  )
}
