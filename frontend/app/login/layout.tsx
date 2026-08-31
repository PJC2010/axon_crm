import type { Metadata } from 'next'

// /login is a client component, so its metadata lives here (audit D5.1: the
// page inherited the homepage title verbatim, diluting search relevance).
export const metadata: Metadata = {
  title: { absolute: 'Sign in to your Axon workspace' },
  description: 'Sign in to Axon to see your ranked territory list, pipeline, and invoices.',
  alternates: { canonical: '/login' },
}

export default function LoginLayout({ children }: { children: React.ReactNode }) {
  return children
}
