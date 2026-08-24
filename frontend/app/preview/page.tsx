import type { Metadata } from 'next'
import { DemoApp } from '@/components/preview/DemoApp'

// The interactive live demo: a working sample workspace with no login and no
// API. All behavior lives in components/preview/DemoApp (client); this server
// wrapper exists so the route can carry crawlable metadata.
export const metadata: Metadata = {
  title: 'Live Demo — try the CRM with sample data',
  description:
    'Try Axon without signing up: drag deals across a real pipeline board, open scored leads to see exactly why they rank, add your own lead, and explore the territory map — all with sample Houston data.',
  alternates: { canonical: '/preview' },
  openGraph: {
    title: 'Axon Live Demo — try the CRM with sample data',
    description:
      'Drag deals, open scored leads, add your own, and explore the territory map. No signup, no login — just the product with sample data.',
    url: '/preview',
  },
}

export default function PreviewPage() {
  return <DemoApp />
}
