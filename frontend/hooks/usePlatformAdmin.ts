'use client'
import { useEffect, useState } from 'react'
import { getMe } from '@/lib/api'
import type { User } from '@/lib/types'

/**
 * Whether the signed-in user is a platform admin (users.is_platform_admin),
 * for the Admin nav link and AdminGuard.
 *
 * Opposite default to useEntitlements: STRICT while loading/on error — the
 * Admin link must never flash for a normal user. The backend guard
 * (require_platform_admin) remains the real enforcement; this only drives
 * visibility. A module-level cache shares one getMe() across header + guard.
 */
let cache: User | null = null
let inflight: Promise<User> | null = null

function load(): Promise<User> {
  if (cache) return Promise.resolve(cache)
  if (!inflight) {
    inflight = getMe()
      .then((u) => { cache = u; return u })
      .finally(() => { inflight = null })
  }
  return inflight
}

/** Clear the cached identity (call on sign-out, next to clearEntitlementsCache). */
export function clearPlatformAdminCache(): void {
  cache = null
  inflight = null
}

export function usePlatformAdmin(): { isPlatformAdmin: boolean; loading: boolean; me: User | null } {
  const [me, setMe] = useState<User | null>(cache)
  const [loading, setLoading] = useState(!cache)

  useEffect(() => {
    let active = true
    // load() resolves immediately off the cache, so this also covers a cache
    // populated between this component's first render and its effect.
    load()
      .then((u) => { if (active) setMe(u) })
      .catch(() => { /* strict: me stays null → not admin */ })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  return { isPlatformAdmin: me?.is_platform_admin === true, loading, me }
}
