import { AdminGuard } from '@/components/admin/AdminGuard'
import { AdminShell } from '@/components/admin/AdminShell'
import { AdminUsers } from '@/components/admin/AdminUsers'

export default function AdminUsersPage() {
  return (
    <AdminGuard>
      <AdminShell current="/admin/users">
        <AdminUsers />
      </AdminShell>
    </AdminGuard>
  )
}
