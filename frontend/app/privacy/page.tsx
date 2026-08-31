import LegalPage, { LegalH2, LegalP, LegalUl } from '@/components/LegalPage'

export const metadata = {
  title: 'Privacy Policy',  // layout template appends "— Axon" (audit D5.1: was doubled)
  description: 'How Axon collects, uses, and protects data — including SMS consent and the public-records property data that powers lead scoring.',
}

export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy Policy" effectiveDate="July 28, 2026">
      <LegalP>
        Axon is a CRM and lead-intelligence platform for local service businesses, operated by
        Castillo &amp; Co LLC (&ldquo;Axon,&rdquo; &ldquo;we,&rdquo; &ldquo;us&rdquo;). This policy
        explains what data we handle, where it comes from, and the choices you have. We&apos;ve
        written it to be read — if anything is unclear, email us and we&apos;ll answer plainly.
      </LegalP>

      <LegalH2>The two kinds of data we handle</LegalH2>
      <LegalP>
        <strong>1. Account data.</strong> Information our customers give us to run their
        workspace: name, business name, email address, login credentials (passwords are stored
        only as salted hashes), team member details, and the CRM records they create — notes,
        tasks, quotes, invoices, expenses, and messages.
      </LegalP>
      <LegalP>
        <strong>2. Property and contact records.</strong> The lead lists at the heart of the
        product. These are assembled from public and licensed sources: county appraisal records
        (such as the Harris County Appraisal District), US Census statistics, NOAA/National
        Weather Service storm reports, building-permit records, and — when a customer enables a
        data provider — licensed property-data and contact-append services. These records can
        include a property&apos;s characteristics, its owner&apos;s name, and, where appended,
        contact details such as a phone number or email address.
      </LegalP>

      <LegalH2>How we use data</LegalH2>
      <LegalUl>
        <li>To operate the service: score properties, populate lead lists, send the messages our customers compose, generate quotes and invoices, and produce reports.</li>
        <li>To run the business: process subscription payments, provide support, and send transactional emails such as verification and password-reset links.</li>
        <li>We do <strong>not</strong> sell our customers&apos; CRM data, run ads on it, or share one customer&apos;s records with another. Every workspace is isolated by account.</li>
      </LegalUl>

      <LegalH2>Service providers we rely on</LegalH2>
      <LegalP>
        We use a small set of processors, each only for its job: Stripe (subscription billing and,
        for customers who enable it, invoice payments), Resend (transactional email), Twilio (SMS
        our customers send and receive), Anthropic (extracting fields from receipt photos our
        customers upload), and — when a customer configures them — property-data and
        contact-append providers. Each receives only the data needed to perform its function.
      </LegalP>

      <LegalH2>Text messages (SMS)</LegalH2>
      <LegalP>
        Axon&apos;s two-way texting and notification features send SMS through Twilio. Here&apos;s
        how that works and what we do with phone numbers.
      </LegalP>
      <LegalUl>
        <li>
          <strong>Consent.</strong> We only send text messages to phone numbers that have given
          consent. Customers using Axon to text their own contacts are required by our{' '}
          <a href="/terms" style={{ color: 'var(--color-accent-300)' }}>Terms of Service</a> to have
          collected that recipient&apos;s consent first. Axon&apos;s own texts to customers (such as
          account and Storm Mode alerts) are sent only after the customer opts in during signup
          or in workspace settings.
        </li>
        <li>
          <strong>No sharing of SMS data.</strong> Mobile phone numbers and SMS opt-in consent are
          never sold, rented, or shared with third parties or affiliates for their marketing or
          promotional purposes. Phone numbers are shared only with Twilio, our messaging provider,
          to deliver the messages themselves.
        </li>
        <li>
          <strong>Opting out.</strong> Reply STOP to any Axon-sent message to unsubscribe from
          texts at any time. Reply HELP for help, or email{' '}
          <a href="mailto:admin@axonhtx.com" style={{ color: 'var(--color-accent-300)' }}>
            admin@axonhtx.com
          </a>.
        </li>
        <li>
          <strong>Frequency and cost.</strong> Message frequency varies by account activity.
          Message and data rates may apply. Carriers are not liable for delayed or undelivered
          messages.
        </li>
      </LegalUl>

      <LegalH2>If you&apos;re a homeowner in an Axon customer&apos;s records</LegalH2>
      <LegalP>
        Axon&apos;s property records originate in public sources — the same appraisal rolls,
        permits, and storm reports available to anyone. Where a contact detail has been appended,
        it came from a licensed data provider. If you&apos;d like to know what an Axon-managed
        list holds about your property, correct it, or have your contact details suppressed from
        Axon-managed enrichment, email us at{' '}
        <a href="mailto:admin@axonhtx.com" style={{ color: 'var(--color-accent-300)' }}>
          admin@axonhtx.com
        </a>{' '}
        and we will respond within 30 days. Residents of Texas and other states with consumer
        privacy laws (including the Texas Data Privacy and Security Act) may exercise their rights
        under those laws through the same address.
      </LegalP>
      <LegalP>
        Our customers are independent businesses and are responsible for how they contact people —
        including compliance with telemarketing laws such as the Telephone Consumer Protection Act
        and the National Do-Not-Call Registry. Our <a href="/terms" style={{ color: 'var(--color-accent-300)' }}>Terms of Service</a>{' '}
        require it.
      </LegalP>

      <LegalH2>Cookies and local storage</LegalH2>
      <LegalP>
        The app stores a login token in your browser&apos;s local storage to keep you signed in.
        We don&apos;t use advertising cookies or cross-site trackers.
      </LegalP>

      <LegalH2>Security and retention</LegalH2>
      <LegalP>
        Data is encrypted in transit, passwords are hashed, one-time links (verification, password
        reset) are stored only as hashes and expire quickly, and workspace data is scoped to your
        account at the query level. We keep your data while your account is active; you can export
        everything to CSV at any time, and you can request deletion of your workspace by email —
        we&apos;ll complete it within 30 days, minus records we must keep for tax or legal reasons.
      </LegalP>

      <LegalH2>Changes and contact</LegalH2>
      <LegalP>
        If we change this policy in a way that matters, we&apos;ll note it here with a new
        effective date and tell active customers by email. Questions, requests, complaints:{' '}
        <a href="mailto:admin@axonhtx.com" style={{ color: 'var(--color-accent-300)' }}>
          admin@axonhtx.com
        </a>.
      </LegalP>
    </LegalPage>
  )
}
