import { AdminGuard } from '@/components/admin/AdminGuard'
import { AdminShell } from '@/components/admin/AdminShell'
import { AdminSecurity } from '@/components/admin/AdminSecurity'

export default function AdminSecurityPage() {
  return (
    <AdminGuard>
      <AdminShell current="/admin/security">
        <AdminSecurity />
      </AdminShell>
    </AdminGuard>
  )
}
