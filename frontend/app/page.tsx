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

// FAQPage structured data (audit D5.5): the same seven Q&As the page renders
// in its FAQ section, as plain text. KEEP IN SYNC with the <details> blocks in
// components/LandingContent.tsx — Google requires the markup to match the
// visible content, so an edit there must be mirrored here.
const faqJsonLd = {
  '@context': 'https://schema.org',
  '@type': 'FAQPage',
  mainEntity: [
    {
      '@type': 'Question',
      name: 'Where does the property data actually come from?',
      acceptedAnswer: {
        '@type': 'Answer',
        text: 'Public records: county appraisal rolls (year built, value, owner, pool, garage), US Census neighborhood data, NOAA/NWS storm reports, and building permits. Axon combines them into a 0\u2013100 score with an A\u2013D grade \u2014 and every property shows the exact signals behind its score, so you never have to take a number on faith.',
      },
    },
    {
      '@type': 'Question',
      name: 'How fast do I see my first list?',
      acceptedAnswer: {
        '@type': 'Answer',
        text: 'The ZIP sample above is instant \u2014 type a ZIP and a scored list renders in seconds. After you sign up, a full territory run (every scored property across your ZIP codes and trade) completes the same day, usually within a few hours.',
      },
    },
    {
      '@type': 'Question',
      name: 'How is this different from buying leads?',
      acceptedAnswer: {
        '@type': 'Answer',
        text: 'A purchased lead is one homeowner who filled out a form \u2014 sold to you and several competitors at once. An Axon list is every promising property in your service area, ranked, with owner and contact details where available. It is built for your account alone, and you pay a flat monthly price, not per name. Nobody on that list has raised a hand yet; the score tells you where to start, and the call is still yours to make.',
      },
    },
    {
      '@type': 'Question',
      name: 'Is there a contract?',
      acceptedAnswer: {
        '@type': 'Answer',
        text: 'Axon is month to month. Cancel anytime. The advertised price is the price, and your data leaves with you.',
      },
    },
    {
      '@type': 'Question',
      name: 'Do I have to rip out QuickBooks or my field-service app?',
      acceptedAnswer: {
        '@type': 'Answer',
        text: 'No. Axon owns the front of your business \u2014 where the next customer comes from and how the deal gets worked. Keep QuickBooks for accounting or Jobber for dispatch as long as you like: Axon imports and exports clean CSVs, so nothing is trapped.',
      },
    },
    {
      '@type': 'Question',
      name: 'Is contacting these homeowners legal?',
      acceptedAnswer: {
        '@type': 'Answer',
        text: 'The data comes from public records, and lots of businesses market from the same sources. Outreach rules still apply to you as the caller \u2014 telemarketing laws like the federal Do-Not-Call registry for cold calls, and consent requirements for texting. Axon shows where every contact came from so you can make honest, informed outreach decisions. See Axon\'s Privacy Policy for details.',
      },
    },
    {
      '@type': 'Question',
      name: 'What happens to my data if I cancel?',
      acceptedAnswer: {
        '@type': 'Answer',
        text: 'It leaves with you. Every list, contact, note, invoice, and expense exports to CSV at any time \u2014 no exit fees, no data hostage-taking.',
      },
    },
  ],
}

export default function LandingPage() {
  return (
    <div className="lp">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(faqJsonLd) }}
      />
      <LandingContent />
    </div>
  )
}
