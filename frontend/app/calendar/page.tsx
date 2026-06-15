import { use } from 'react'
import { AuthGuard } from '@/components/AuthGuard'
import { CalendarScreen } from '@/components/CalendarScreen'

export default function CalendarPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}) {
  // Deep-link support: /calendar?lead=123 prefills the appointment form for that
  // lead (used by the "Book appointment" action in the lead drawer).
  const params = use(searchParams)
  const leadParam = typeof params.lead === 'string' ? parseInt(params.lead, 10) : NaN

  return (
    <AuthGuard>
      <CalendarScreen prefillLeadId={Number.isFinite(leadParam) ? leadParam : undefined} />
    </AuthGuard>
  )
}
