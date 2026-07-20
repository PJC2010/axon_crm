import type { MetadataRoute } from 'next'

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? 'https://axonhtx.com'

// Only the marketing/legal/auth-entry pages should be crawled. Everything else
// is either behind auth (useless, thin pages to a crawler) or carries a private
// token in the URL (/q/, /pay/) and must never appear in an index.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: '*',
        allow: ['/', '/hcad-data', '/login', '/signup', '/privacy', '/terms'],
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
          '/marketing',
          '/settings',
          '/preview',
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
