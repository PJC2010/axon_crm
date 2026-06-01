'use client'
import { AuthGuard } from '@/components/AuthGuard'
import { BookkeepingDashboard } from '@/components/BookkeepingDashboard'

export default function BookkeepingPage() {
  return (
    <AuthGuard>
      <BookkeepingDashboard />
    </AuthGuard>
  )
}
