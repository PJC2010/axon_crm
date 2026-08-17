import { AdminGuard } from '@/components/admin/AdminGuard'
import { AdminShell } from '@/components/admin/AdminShell'
import { AdminOrgDetail } from '@/components/admin/AdminOrgDetail'

// Next 16: route params are async and must be awaited.
export default async function AdminOrgDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return (
    <AdminGuard>
      <AdminShell current="/admin/orgs">
        <AdminOrgDetail accountId={Number(id)} />
      </AdminShell>
    </AdminGuard>
  )
}
