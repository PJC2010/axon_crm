'use client'
import Link from 'next/link'
import { NAV_ITEMS, isNavVisible } from '@/lib/nav'
import { useEntitlements } from '@/hooks/useEntitlements'

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
  const items = NAV_ITEMS.filter((it) => it.href !== current && isNavVisible(it, hasModule))

  if (variant === 'desktop') {
    return (
      <>
        {items.map((it) => {
          const Icon = it.icon
          return (
            <Link
              key={it.href}
              href={it.href}
              title={it.label}
              className="dash-icon-btn"
              style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '0 10px', textDecoration: 'none', color: 'inherit', fontSize: 13 }}
            >
              <Icon size={13} strokeWidth={1.5} />
              <span>{it.shortLabel ?? it.label}</span>
            </Link>
          )
        })}
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
            {it.label}
          </Link>
        )
      })}
    </>
  )
}
