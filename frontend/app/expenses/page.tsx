'use client'
import { AuthGuard } from '@/components/AuthGuard'
import { ExpenseTracker } from '@/components/ExpenseTracker'

export default function ExpensesPage() {
  return (
    <AuthGuard>
      <ExpenseTracker />
    </AuthGuard>
  )
}
