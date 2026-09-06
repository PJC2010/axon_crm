import { AdminGuard } from '@/components/admin/AdminGuard'
import { AdminShell } from '@/components/admin/AdminShell'
import { AdminData } from '@/components/admin/AdminData'

export default function AdminDataPage() {
  return (
    <AdminGuard>
      <AdminShell current="/admin/data">
        <AdminData />
      </AdminShell>
    </AdminGuard>
  )
}
