import { AdminGuard } from '@/components/admin/AdminGuard'
import { AdminShell } from '@/components/admin/AdminShell'
import { AdminOrgs } from '@/components/admin/AdminOrgs'

export default function AdminOrgsPage() {
  return (
    <AdminGuard>
      <AdminShell current="/admin/orgs">
        <AdminOrgs />
      </AdminShell>
    </AdminGuard>
  )
}
