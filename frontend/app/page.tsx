import type { Metadata } from 'next'
import './landing.css'
import LandingContent from '@/components/LandingContent'

// Root page owns the un-templated title (the layout template would render
// "X — Axon"; here we want full control of the ~60-char SERP title).
export const metadata: Metadata = {
  title: {
    absolute: 'Axon — Territory intelligence for Harris County contractors',
  },
  description:
    'Rank the properties in your Harris County service area using appraisal, permit, equity, and storm data. Every score explained. No shared leads. No contracts.',
  alternates: { canonical: '/' },
  openGraph: {
    url: '/',
    title: 'Axon — Territory intelligence for Harris County contractors',
    description:
      'Know which properties are worth calling first. Axon ranks your Harris County ZIP codes from appraisal, permit, equity, and storm data — and shows the signals behind every score.',
  },
}

// Structured data: SoftwareApplication (with real on-page pricing) nested with
// the operating Organization. Values must always mirror visible page content.
const jsonLd = {
  '@context': 'https://schema.org',
  '@type': 'SoftwareApplication',
  name: 'Axon',
  applicationCategory: 'BusinessApplication',
  operatingSystem: 'Web',
  description:
    'Territory intelligence for service contractors in Harris County, Texas. Scores and ranks every property in a service area using Harris County appraisal records, permits, equity, and storm data, shows the signals behind every score, and adds quoting, invoicing, and pipeline management to work the list.',
  offers: {
    '@type': 'AggregateOffer',
    priceCurrency: 'USD',
    lowPrice: '49',
    highPrice: '249',
    offerCount: 3,
    areaServed: {
      '@type': 'AdministrativeArea',
      name: 'Harris County, Texas',
    },
  },
  audience: {
    '@type': 'BusinessAudience',
    name: 'Service contractors and small service businesses in Harris County, Texas',
  },
  publisher: {
    '@type': 'Organization',
    name: 'Castillo & Co LLC',
    areaServed: { '@type': 'AdministrativeArea', name: 'Harris County, Texas' },
    location: { '@type': 'Place', address: { '@type': 'PostalAddress', addressLocality: 'Houston', addressRegion: 'TX', addressCountry: 'US' } },
  },
}

export default function LandingPage() {
  return (
    <div className="lp">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <LandingContent />
    </div>
  )
}
