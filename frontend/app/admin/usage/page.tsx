import { AdminGuard } from '@/components/admin/AdminGuard'
import { AdminShell } from '@/components/admin/AdminShell'
import { AdminUsage } from '@/components/admin/AdminUsage'

export default function AdminUsagePage() {
  return (
    <AdminGuard>
      <AdminShell current="/admin/usage">
        <AdminUsage />
      </AdminShell>
    </AdminGuard>
  )
}
