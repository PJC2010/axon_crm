import type { MetadataRoute } from 'next'

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? 'https://axonhtx.com'

// Only pages a search engine should rank. App routes are deliberately absent —
// they're disallowed in robots.ts and noindexed via middleware.
export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: `${SITE_URL}/`, changeFrequency: 'weekly', priority: 1 },
    { url: `${SITE_URL}/preview`, changeFrequency: 'monthly', priority: 0.8 },
    { url: `${SITE_URL}/hcad-data`, changeFrequency: 'monthly', priority: 0.7 },
    { url: `${SITE_URL}/vs/axon-vs-angi`, changeFrequency: 'monthly', priority: 0.7 },
    { url: `${SITE_URL}/vs/axon-vs-salesrabbit`, changeFrequency: 'monthly', priority: 0.7 },
    { url: `${SITE_URL}/vs/axon-vs-ladder`, changeFrequency: 'monthly', priority: 0.7 },
    { url: `${SITE_URL}/signup`, changeFrequency: 'monthly', priority: 0.8 },
    { url: `${SITE_URL}/login`, changeFrequency: 'yearly', priority: 0.3 },
    { url: `${SITE_URL}/privacy`, changeFrequency: 'yearly', priority: 0.2 },
    { url: `${SITE_URL}/terms`, changeFrequency: 'yearly', priority: 0.2 },
  ]
}
