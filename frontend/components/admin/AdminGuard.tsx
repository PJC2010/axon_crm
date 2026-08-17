'use client'
import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { getToken } from '@/lib/auth'
import { usePlatformAdmin } from '@/hooks/usePlatformAdmin'

/**
 * Route guard for /admin pages: token present AND is_platform_admin, else
 * bounce (mirrors AuthGuard). Renders nothing until confirmed so admin UI
 * never flashes for a normal user. The backend's require_platform_admin is
 * the real enforcement — this is only UX.
 */
export function AdminGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const [hasToken, setHasToken] = useState(false)
  const { isPlatformAdmin, loading } = usePlatformAdmin()

  useEffect(() => {
    if (!getToken()) router.replace('/login')
    else setHasToken(true)
  }, [router])

  useEffect(() => {
    if (hasToken && !loading && !isPlatformAdmin) router.replace('/home')
  }, [hasToken, loading, isPlatformAdmin, router])

  if (!hasToken || loading || !isPlatformAdmin) return null
  return <>{children}</>
}
