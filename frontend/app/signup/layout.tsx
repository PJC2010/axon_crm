import type { Metadata } from 'next'

// /signup is a client component, so its metadata lives here (audit D5.1: the
// page inherited the homepage title verbatim, diluting search relevance).
export const metadata: Metadata = {
  title: { absolute: 'Start free — 14 days, no credit card — Axon' },
  description:
    'Create your Axon workspace in under a minute: company name, work email, password. 14 days free, no credit card, month to month.',
  alternates: { canonical: '/signup' },
}

export default function SignupLayout({ children }: { children: React.ReactNode }) {
  return children
}
