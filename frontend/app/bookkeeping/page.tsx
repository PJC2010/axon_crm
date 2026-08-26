'use client'
import { use } from 'react'
import { AuthGuard } from '@/components/AuthGuard'
import { BookkeepingDashboard } from '@/components/BookkeepingDashboard'

const TABS = ['overview', 'quotes', 'invoices', 'ar', 'pnl'] as const
type Tab = (typeof TABS)[number]

export default function BookkeepingPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}) {
  // Deep-link support: /bookkeeping?tab=quotes&lead=123 opens the quote builder
  // prefilled from that lead, and ?tab=invoices&lead=123 opens the invoice
  // builder prefilled (both used by the pipeline's next-step hint).
  const params = use(searchParams)
  const tabParam = typeof params.tab === 'string' && (TABS as readonly string[]).includes(params.tab)
    ? (params.tab as Tab)
    : undefined
  const leadParam = typeof params.lead === 'string' ? parseInt(params.lead, 10) : NaN

  return (
    <AuthGuard>
      <BookkeepingDashboard
        initialTab={tabParam}
        prefillLeadId={Number.isFinite(leadParam) ? leadParam : undefined}
      />
    </AuthGuard>
  )
}
