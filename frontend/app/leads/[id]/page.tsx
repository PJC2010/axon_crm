import { LeadDetail } from '@/components/LeadDetail'
import { AuthGuard } from '@/components/AuthGuard'

// Next 16: route params are async and must be awaited.
export default async function LeadDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return (
    <AuthGuard>
      <LeadDetail leadId={Number(id)} />
    </AuthGuard>
  )
}
