import Link from 'next/link'
import { Compass } from 'lucide-react'

export const metadata = {
  // The root layout applies a "%s — Axon" template, so this is the bare title.
  title: 'Page not found',
  description: 'That page does not exist. Head back to your dashboard or the map.',
}

/**
 * Custom 404. The default Next.js page is an unstyled black slab with no way
 * back, which is a dead end in every flow that mistypes a URL or follows a
 * stale link — so this one carries the app's surfaces and offers the two
 * destinations that resolve it.
 */
export default function NotFound() {
  return (
    <main id="main"
      style={{
        minHeight: '100dvh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px',
      }}
    >
      <div style={{ textAlign: 'center', maxWidth: 420 }}>
        <Compass
          size={48}
          strokeWidth={1}
          aria-hidden
          style={{ color: 'var(--color-ink-300)', marginBottom: 16 }}
        />
        <p className="t-eyebrow" style={{ marginBottom: 8 }}>Error 404</p>
        <h1
          className="t-title"
          style={{ fontSize: 26, margin: '0 0 10px', textWrap: 'balance' }}
        >
          We couldn&apos;t find that page
        </h1>
        <p
          style={{
            margin: '0 0 24px',
            fontSize: 14,
            lineHeight: 1.6,
            color: 'var(--color-ink-500)',
            textWrap: 'pretty',
          }}
        >
          The link may be out of date, or the record may have been archived.
        </p>
        <div style={{ display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap' }}>
          <Link
            href="/home"
            className="btn-primary"
            style={{ textDecoration: 'none', padding: '10px 20px' }}
          >
            Back to dashboard
          </Link>
          <Link
            href="/"
            className="btn-secondary"
            style={{ textDecoration: 'none', padding: '10px 20px' }}
          >
            Go to the home page
          </Link>
        </div>
      </div>
    </main>
  )
}
