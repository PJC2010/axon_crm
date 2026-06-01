import { HomeDashboard } from '@/components/HomeDashboard'
import { AuthGuard } from '@/components/AuthGuard'

export default function HomePage() {
  return <AuthGuard><HomeDashboard /></AuthGuard>
}
