import { Suspense } from 'react'
import { Dashboard } from '@/components/Dashboard'
import { AuthGuard } from '@/components/AuthGuard'

export default function DashboardPage() {
  return (
    <AuthGuard>
      <Suspense fallback={null}>
        <Dashboard />
      </Suspense>
    </AuthGuard>
  )
}
