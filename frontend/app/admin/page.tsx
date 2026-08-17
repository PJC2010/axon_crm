import { AdminGuard } from '@/components/admin/AdminGuard'
import { AdminShell } from '@/components/admin/AdminShell'
import { AdminOverview } from '@/components/admin/AdminOverview'

export default function AdminPage() {
  return (
    <AdminGuard>
      <AdminShell current="/admin">
        <AdminOverview />
      </AdminShell>
    </AdminGuard>
  )
}
