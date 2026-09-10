import { AdminGuard } from '@/components/admin/AdminGuard'
import { AdminShell } from '@/components/admin/AdminShell'
import { AdminOps } from '@/components/admin/AdminOps'

export default function AdminOpsPage() {
  return (
    <AdminGuard>
      <AdminShell current="/admin/ops">
        <AdminOps />
      </AdminShell>
    </AdminGuard>
  )
}
