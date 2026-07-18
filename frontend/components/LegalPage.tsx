import Link from 'next/link'
import type { ReactNode } from 'react'

// Shared shell for the public legal pages (/privacy, /terms). Server-rendered,
// plain typography — these pages exist to be read, not to impress.
export default function LegalPage({
  title,
  effectiveDate,
  children,
}: {
  title: string
  effectiveDate: string
  children: ReactNode
}) {
  return (
    <div style={{ minHeight: '100vh', background: 'var(--color-paper)' }}>
      <nav
        style={{
          height: 64,
          borderBottom: '1px solid var(--color-ink-200)',
          display: 'flex',
          alignItems: 'center',
        }}
      >
        <div style={{ maxWidth: 760, margin: '0 auto', width: '100%', padding: '0 24px' }}>
          <Link
            href="/"
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 19,
              fontWeight: 600,
              color: 'var(--color-ink-900)',
              textDecoration: 'none',
            }}
          >
            Axon
          </Link>
        </div>
      </nav>

      <main className="legal-body" style={{ maxWidth: 760, margin: '0 auto', padding: '48px 24px 88px' }}>
        <h1
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 32,
            fontWeight: 600,
            margin: '0 0 6px',
            color: 'var(--color-ink-900)',
          }}
        >
          {title}
        </h1>
        <p style={{ fontSize: 13, color: 'var(--color-ink-400)', margin: '0 0 36px' }}>
          Effective {effectiveDate} · Axon, a Castillo &amp; Co LLC company ·{' '}
          <a href="mailto:admin@axonhtx.com" style={{ color: 'var(--color-accent)' }}>
            admin@axonhtx.com
          </a>
        </p>
        {children}
      </main>

      <footer
        style={{
          borderTop: '1px solid var(--color-ink-200)',
          padding: '24px 0',
          fontSize: 12,
          color: 'var(--color-ink-400)',
        }}
      >
        <div
          style={{
            maxWidth: 760,
            margin: '0 auto',
            padding: '0 24px',
            display: 'flex',
            gap: 18,
            flexWrap: 'wrap',
          }}
        >
          <span>© 2026 Axon, a Castillo &amp; Co LLC company.</span>
          <Link href="/privacy" style={{ color: 'var(--color-ink-500)' }}>Privacy</Link>
          <Link href="/terms" style={{ color: 'var(--color-ink-500)' }}>Terms</Link>
          <Link href="/" style={{ color: 'var(--color-ink-500)' }}>Home</Link>
        </div>
      </footer>
    </div>
  )
}

// Typographic helpers so the two pages stay consistent without a CSS file.
export function LegalH2({ children }: { children: ReactNode }) {
  return (
    <h2
      style={{
        fontFamily: 'var(--font-display)',
        fontSize: 20,
        fontWeight: 600,
        margin: '36px 0 12px',
        color: 'var(--color-ink-900)',
      }}
    >
      {children}
    </h2>
  )
}

export function LegalP({ children }: { children: ReactNode }) {
  return (
    <p style={{ fontSize: 15, lineHeight: 1.65, color: 'var(--color-ink-700)', margin: '0 0 14px' }}>
      {children}
    </p>
  )
}

export function LegalUl({ children }: { children: ReactNode }) {
  return (
    <ul
      style={{
        fontSize: 15,
        lineHeight: 1.65,
        color: 'var(--color-ink-700)',
        margin: '0 0 14px',
        paddingLeft: 24,
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
      }}
    >
      {children}
    </ul>
  )
}
