import type { MetadataRoute } from 'next'

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? 'https://axonhtx.com'

// Only the marketing/legal/auth-entry pages should be crawled. Everything else
// is either behind auth (useless, thin pages to a crawler) or carries a private
// token in the URL (/q/, /pay/) and must never appear in an index.
// /preview is deliberately crawlable: it's the no-login interactive demo — a
// marketing surface, not an app route (its /preview/dev component gallery is
// still excluded).
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: '*',
        allow: ['/', '/hcad-data', '/vs/', '/login', '/signup', '/privacy', '/terms', '/preview'],
        disallow: [
          '/home',
          '/dashboard',
          '/leads',
          '/map',
          '/pipeline',
          '/tasks',
          '/calls',
          '/expenses',
          '/bookkeeping',
          '/settings',
          '/preview/dev',
          '/design-system',
          '/q/',
          '/pay/',
          '/reset-password',
          '/verify-email',
        ],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
  }
}
