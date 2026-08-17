import { AdminGuard } from '@/components/admin/AdminGuard'
import { AdminShell } from '@/components/admin/AdminShell'
import { AdminAudit } from '@/components/admin/AdminAudit'

export default function AdminAuditPage() {
  return (
    <AdminGuard>
      <AdminShell current="/admin/audit">
        <AdminAudit />
      </AdminShell>
    </AdminGuard>
  )
}
