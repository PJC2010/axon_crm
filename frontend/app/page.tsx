import type { Metadata } from 'next'
import './landing.css'
import LandingContent from '@/components/LandingContent'

// Root page owns the un-templated title (the layout template would render
// "X — Axon"; here we want full control of the ~60-char SERP title).
export const metadata: Metadata = {
  title: {
    absolute: 'Axon — Data-scored leads for Houston home service contractors',
  },
  description:
    'Exclusive, ranked homeowner leads for Greater Houston contractors — scored from Harris County records, permits, equity, and storm data. No shared leads. Free 14-day trial.',
  alternates: { canonical: '/' },
  openGraph: {
    url: '/',
    title: 'Axon — Data-scored leads for Houston home service contractors',
    description:
      'Every property in your Greater Houston ZIP, scored and ranked from Harris County records, permits, equity, and storm data. Yours alone — no shared leads, no contracts.',
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
    'Lead intelligence CRM for home service contractors in the Greater Houston area. Scores every property in a service area using Harris County appraisal records, permits, equity, and storm data, and provides an exclusive ranked call list plus quoting, invoicing, and pipeline management.',
  offers: {
    '@type': 'AggregateOffer',
    priceCurrency: 'USD',
    lowPrice: '49',
    highPrice: '249',
    offerCount: 3,
    areaServed: {
      '@type': 'AdministrativeArea',
      name: 'Greater Houston, Texas',
    },
  },
  audience: {
    '@type': 'BusinessAudience',
    name: 'Home service contractors and small service businesses in the Greater Houston area',
  },
  publisher: {
    '@type': 'Organization',
    name: 'Castillo & Co LLC',
    areaServed: { '@type': 'AdministrativeArea', name: 'Greater Houston, Texas' },
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
