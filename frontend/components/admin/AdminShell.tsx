'use client'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { ArrowLeft, LogOut } from 'lucide-react'
import { clearToken } from '@/lib/auth'
import { clearEntitlementsCache } from '@/hooks/useEntitlements'
import { clearPlatformAdminCache } from '@/hooks/usePlatformAdmin'

const TABS = [
  { href: '/admin', label: 'Overview' },
  { href: '/admin/orgs', label: 'Orgs' },
  { href: '/admin/users', label: 'Users' },
  { href: '/admin/security', label: 'Security' },
  { href: '/admin/audit', label: 'Audit' },
]

/** Shared chrome for every /admin page: header + tab nav + content container. */
export function AdminShell({ current, children }: { current: string; children: React.ReactNode }) {
  const router = useRouter()

  function handleSignOut() {
    clearToken()
    clearEntitlementsCache()
    clearPlatformAdminCache()
    router.push('/login')
  }

  const isActive = (href: string) =>
    href === '/admin' ? current === '/admin' : current.startsWith(href)

  return (
    <div style={{ minHeight: '100dvh', background: 'var(--color-paper)' }}>
      <header
        style={{
          height: 64, padding: '0 20px',
          background: 'var(--color-paper)',
          borderBottom: '1px solid var(--color-ink-200)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          position: 'sticky', top: 0, zIndex: 10,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Link href="/home" style={{ display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none', color: 'inherit' }}>
            <svg width="26" height="26" viewBox="0 0 32 32" fill="none" aria-hidden="true">
              <mask id="axon-mark-admin">
                <rect width="32" height="32" fill="white" />
                <rect x="2" y="14.5" width="28" height="3" rx="1.5" fill="black" />
                <rect x="14.5" y="2" width="3" height="28" rx="1.5" fill="black" />
              </mask>
              <polygon points="16,5 27,16 16,27 5,16" fill="var(--color-accent)" mask="url(#axon-mark-admin)" />
              <circle cx="16" cy="16" r="1.5" fill="var(--color-ink-900)" />
            </svg>
            <span style={{ fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 600, letterSpacing: '-0.01em', color: 'var(--color-ink-900)' }}>
              Axon
            </span>
          </Link>
          <span style={{ color: 'var(--color-ink-300)', fontSize: 14 }}>·</span>
          <span className="t-eyebrow">Platform Admin</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Link href="/home" title="Back to app" className="dash-icon-btn"
            style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '0 10px', textDecoration: 'none', color: 'inherit', fontSize: 13 }}>
            <ArrowLeft size={13} strokeWidth={1.5} />
            <span>Back to app</span>
          </Link>
          <button onClick={handleSignOut} title="Sign out" className="dash-icon-btn">
            <LogOut size={14} strokeWidth={1.5} />
          </button>
        </div>
      </header>

      <nav
        style={{
          display: 'flex', gap: 4, padding: '10px 20px 0',
          borderBottom: '1px solid var(--color-ink-200)',
          background: 'var(--color-paper)',
          overflowX: 'auto',
        }}
      >
        {TABS.map((t) => (
          <Link
            key={t.href}
            href={t.href}
            style={{
              padding: '8px 14px 10px',
              fontSize: 13, fontWeight: 500,
              textDecoration: 'none', whiteSpace: 'nowrap',
              color: isActive(t.href) ? 'var(--color-ink-900)' : 'var(--color-ink-500)',
              borderBottom: isActive(t.href) ? '2px solid var(--color-accent)' : '2px solid transparent',
              marginBottom: -1,
            }}
          >
            {t.label}
          </Link>
        ))}
      </nav>

      <main id="main" style={{ maxWidth: 1100, margin: '0 auto', padding: '22px 20px 60px' }}>
        {children}
      </main>
    </div>
  )
}
