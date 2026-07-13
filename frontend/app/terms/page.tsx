import LegalPage, { LegalH2, LegalP, LegalUl } from '@/components/LegalPage'

export const metadata = {
  title: 'Terms of Service — Axon',
  description: 'The agreement between Axon and the businesses that use it: plans, billing, acceptable use, and data ownership.',
}

export default function TermsPage() {
  return (
    <LegalPage title="Terms of Service" effectiveDate="July 12, 2026">
      <LegalP>
        These terms are the agreement between Castillo &amp; Co LLC (&ldquo;Axon,&rdquo;
        &ldquo;we&rdquo;) and the business that opens an Axon account (&ldquo;you&rdquo;). By
        creating an account or using the service you accept them. We&apos;ve kept them short and
        in plain language on purpose.
      </LegalP>

      <LegalH2>Your account</LegalH2>
      <LegalP>
        You&apos;re responsible for your login credentials, for the people you invite to your
        workspace, and for making sure your use of Axon is on behalf of a business (Axon is a
        business tool, not a consumer service). Keep your contact email current — it&apos;s how we
        reach you about your account.
      </LegalP>

      <LegalH2>Plans, trials, and billing</LegalH2>
      <LegalUl>
        <li>New accounts start with a free trial of the full feature set — no credit card required. When the trial ends without a subscription, the account moves to the core (Starter-level) feature set; your data is never held hostage.</li>
        <li>Paid plans are billed monthly through Stripe at the advertised price. No annual contracts, no cancellation fees.</li>
        <li>You can change or cancel your plan anytime from the billing portal; cancellation takes effect at the end of the paid period, and we don&apos;t pro-rate partial months.</li>
        <li>If a charge fails we&apos;ll retry and email you before access changes.</li>
      </LegalUl>

      <LegalH2>Acceptable use — especially outreach</LegalH2>
      <LegalP>
        Axon surfaces property records and, where you enable a data provider, appended contact
        details. <strong>You are the caller of record for your outreach</strong>, and you agree to
        comply with the laws that govern it, including the Telephone Consumer Protection Act
        (TCPA), the Telemarketing Sales Rule and National Do-Not-Call Registry, state
        telemarketing rules, and consent requirements for SMS. You also agree not to abuse the
        service: no unlawful content, no attempts to access other tenants&apos; data, no resale of
        the data outside your business, and no use of the platform to harass anyone.
      </LegalP>

      <LegalH2>Your data</LegalH2>
      <LegalP>
        The records in your workspace are yours. You can export them to CSV at any time, and if
        you leave we&apos;ll delete your workspace on request (see the{' '}
        <a href="/privacy" style={{ color: 'var(--color-accent)' }}>Privacy Policy</a>). You grant
        us only the license needed to host, process, and display that data to run the service.
      </LegalP>

      <LegalH2>Data accuracy</LegalH2>
      <LegalP>
        Scores, property facts, and appended contact details are assembled from public records and
        third-party providers. They are provided <strong>as-is, as decision support</strong> — not
        as a guarantee that a roof is old, an owner lives at an address, or a phone number is
        current. Verify before you act on anything consequential.
      </LegalP>

      <LegalH2>Warranties and liability</LegalH2>
      <LegalP>
        We work to keep Axon fast and available, but the service is provided &ldquo;as is&rdquo;
        without warranties of any kind, and we may change features over time. To the maximum
        extent the law allows, our total liability for any claim is limited to the amount you paid
        us in the twelve months before the claim, and neither side is liable for indirect or
        consequential damages. Nothing here limits liability that can&apos;t be limited by law.
      </LegalP>

      <LegalH2>Ending the agreement</LegalH2>
      <LegalP>
        You can stop using Axon and cancel at any time. We may suspend or terminate an account
        that violates these terms — where practical, we&apos;ll warn you first and give you a
        window to export your data.
      </LegalP>

      <LegalH2>The boring-but-necessary part</LegalH2>
      <LegalP>
        These terms are governed by the laws of the State of Texas, with venue in Harris County.
        If we update the terms in a way that matters, we&apos;ll post the new version here with a
        new effective date and email active customers. Questions:{' '}
        <a href="mailto:castillop92@gmail.com" style={{ color: 'var(--color-accent)' }}>
          castillop92@gmail.com
        </a>.
      </LegalP>
    </LegalPage>
  )
}
