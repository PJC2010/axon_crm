import type { Metadata } from 'next'
import '../../landing.css'
import { VsPage } from '@/components/vs/VsPage'
import { getVsCompetitor } from '@/lib/vsData'

const data = getVsCompetitor('axon-vs-angi')!

export const metadata: Metadata = {
  title: { absolute: data.title },
  description: data.metaDescription,
  alternates: { canonical: '/vs/axon-vs-angi' },
  openGraph: { url: '/vs/axon-vs-angi', title: data.title, description: data.metaDescription },
}

export default function Page() {
  return <VsPage data={data} />
}
