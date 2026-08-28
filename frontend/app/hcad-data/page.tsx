import type { Metadata } from 'next'
import Link from 'next/link'
import type { ReactNode } from 'react'

// SEO content page: targets HCAD-adjacent searches only Greater Houston
// contractors make ("HCAD data", "Harris County property records leads").
// Deliberately modeled on the LegalPage shell — server-rendered, zero JS,
// plain typography — so it loads instantly and reads like an explainer,
// not an ad.

export const metadata: Metadata = {
  title: 'HCAD data, explained for Houston contractors',
  description:
    'What Harris County appraisal records reveal about your next customer — home age, equity, garages, sale history — and how Axon turns them into a ranked call list.',
  alternates: { canonical: '/hcad-data' },
  openGraph: {
    url: '/hcad-data',
    title: 'HCAD data, explained for Houston contractors',
    description:
      'What Harris County appraisal records reveal about your next customer, and how Axon turns a million public parcels into a ranked, exclusive call list.',
  },
}

const jsonLd = {
  '@context': 'https://schema.org',
  '@type': 'Article',
  headline: 'HCAD data, explained for Houston contractors',
  description:
    'How Harris County Appraisal District records — home age, appraised value, garages, sale history — become scored, graded leads for Greater Houston home service contractors.',
  author: { '@type': 'Organization', name: 'Axon' },
  publisher: { '@type': 'Organization', name: 'Castillo & Co LLC' },
  about: { '@type': 'GovernmentOrganization', name: 'Harris County Appraisal District' },
  audience: {
    '@type': 'BusinessAudience',
    name: 'Home service contractors in the Greater Houston area',
  },
}

function H2({ children }: { children: ReactNode }) {
  return (
    <h2
      style={{
        fontFamily: 'var(--font-display)',
        fontSize: 22,
        fontWeight: 600,
        color: 'var(--color-ink-900)',
        margin: '40px 0 12px',
      }}
    >
      {children}
    </h2>
  )
}

function P({ children }: { children: ReactNode }) {
  return (
    <p style={{ fontSize: 15.5, lineHeight: 1.7, color: 'var(--color-ink-700)', margin: '0 0 16px' }}>
      {children}
    </p>
  )
}

export default function HcadDataPage() {
  return (
    <div style={{ minHeight: '100dvh', background: 'var(--color-paper)' }}>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />

      <nav style={{ height: 64, borderBottom: '1px solid var(--color-ink-200)', display: 'flex', alignItems: 'center' }}>
        <div style={{ maxWidth: 760, margin: '0 auto', width: '100%', padding: '0 24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Link href="/" style={{ fontFamily: 'var(--font-display)', fontSize: 19, fontWeight: 600, color: 'var(--color-ink-900)', textDecoration: 'none' }}>
            Axon
          </Link>
          <Link
            href="/signup"
            style={{
              background: 'var(--color-accent)', color: 'var(--text-on-accent)', fontSize: 13.5, fontWeight: 600,
              padding: '8px 16px', borderRadius: 6, textDecoration: 'none',
            }}
          >
            Start free trial
          </Link>
        </div>
      </nav>

      <main id="main" style={{ maxWidth: 760, margin: '0 auto', padding: '48px 24px 88px' }}>
        <h1
          style={{
            fontFamily: 'var(--font-display)', fontSize: 34, fontWeight: 600,
            margin: '0 0 10px', color: 'var(--color-ink-900)', lineHeight: 1.2,
          }}
        >
          HCAD data, explained for contractors
        </h1>
        <p style={{ fontSize: 16, color: 'var(--color-ink-400)', margin: '0 0 36px' }}>
          The county already knows a lot about your next customer. Here&apos;s what&apos;s in the
          record — and how Axon turns it into a call list.
        </p>

        <H2>What HCAD actually is</H2>
        <P>
          The Harris County Appraisal District (HCAD) is the public agency that appraises every
          taxable property in Harris County — well over a million parcels — to set property taxes.
          Because appraisals are public record, anyone can look up a home&apos;s year built,
          appraised value, building details, and sale history. Most people only ever do it to
          protest their own taxes. For a contractor, it&apos;s something else entirely: a map of
          which homes in your ZIP are aging into your services.
        </P>

        <H2>What one property record tells you</H2>
        <P>
          <strong>Year built.</strong> A roof, a water heater, an HVAC system — every major
          component has a lifespan. A neighborhood platted in 2004 is a neighborhood full of
          20-year-old roofs. Home age is the single most predictive public signal for
          replacement-driven work.
        </P>
        <P>
          <strong>Appraised value and sale history.</strong> Value together with how long ago the
          home last sold is a reasonable proxy for equity — and homeowners with equity approve
          bigger tickets and finance less. A home that hasn&apos;t changed hands in fifteen years
          is also a home whose systems likely haven&apos;t either.
        </P>
        <P>
          <strong>Improvement details.</strong> Garage spaces, building area, lot size. A
          three-car garage means more doors, more concrete, more electrical load — and a
          homeowner who invests in the property.
        </P>

        <H2>One record is trivia. A million records is a strategy.</H2>
        <P>
          Nothing above is secret — that&apos;s the point. The problem is scale: nobody running a
          crew has time to read a million parcel records, cross-reference them with permits, and
          decide who to call Monday morning. That&apos;s the part Axon does. Axon combines HCAD
          records with US Census income data, building permit filings, and NOAA storm reports,
          scores every property in your service area from 0–100, and grades it A through D. You
          get a ranked call list for your ZIPs — and every property shows the data behind its score.
        </P>
        <P>
          Because the list is built from public data — not bought from a form-fill marketplace —
          it belongs to your account alone. No shared inquiry, sold to you and several
          competitors at the same time.
        </P>

        <H2>Common questions</H2>
        <P>
          <strong>Is using HCAD data legal?</strong> Yes. Appraisal records are public by Texas
          law, and Axon uses them the way the county publishes them. How we handle property data
          — including opt-outs — is covered plainly in our <Link href="/privacy" style={{ color: 'var(--color-accent-300)' }}>privacy policy</Link>.
        </P>
        <P>
          <strong>What areas do you cover?</strong> Harris County today, with Greater Houston
          expansion underway. If your territory reaches into a neighboring county, tell us —
          coverage requests drive our roadmap.
        </P>
        <P>
          <strong>Does this replace referrals?</strong> No — it fills the gaps between them. Data
          points the way; people close the job.
        </P>

        <div
          style={{
            marginTop: 48, padding: '28px 28px 30px', border: '1px solid var(--color-ink-200)',
            borderRadius: 10, background: '#fff',
          }}
        >
          <p style={{ fontFamily: 'var(--font-display)', fontSize: 19, fontWeight: 600, color: 'var(--color-ink-900)', margin: '0 0 6px' }}>
            See your own ZIP scored
          </p>
          <p style={{ fontSize: 14.5, color: 'var(--color-ink-700)', margin: '0 0 18px' }}>
            Free 14-day trial. Flat monthly plans, no contracts, no per-lead fees.
          </p>
          <Link
            href="/signup"
            style={{
              display: 'inline-block', background: 'var(--color-accent)', color: 'var(--text-on-accent)',
              fontSize: 14.5, fontWeight: 600, padding: '10px 20px', borderRadius: 6,
              textDecoration: 'none',
            }}
          >
            Start free trial
          </Link>
        </div>
      </main>
    </div>
  )
}
