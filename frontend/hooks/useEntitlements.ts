'use client'
import { useEffect, useState } from 'react'
import { getAccountFeatures } from '@/lib/api'
import { getToken } from '@/lib/auth'
import type { AccountFeatures, ModuleKey, ScoringQuota } from '@/lib/types'

/**
 * Account feature-module entitlements for gating nav and UI.
 *
 * Resolution is permissive by design (mirrors the backend): until features load,
 * and if the request fails, modules are treated as enabled so we never hide a
 * feature the user is actually paying for because of a transient error. The
 * backend guards remain the real enforcement; this hook only drives visibility.
 *
 * A module-level cache shares one request across the components that mount on a
 * page (header nav + page gate), so we don't refetch per component.
 */
let cache: AccountFeatures | null = null
let inflight: Promise<AccountFeatures> | null = null
const listeners = new Set<(f: AccountFeatures) => void>()

function load(): Promise<AccountFeatures> {
  if (cache) return Promise.resolve(cache)
  // No session → nothing to fetch. This matters on public pages (/preview
  // renders entitlements-aware components like WonCelebration): the request
  // would 401 and api.ts's 401 handler hard-redirects to /login. Rejecting
  // here keeps the hook on its permissive no-features path instead.
  if (!getToken()) return Promise.reject(new Error('not signed in'))
  if (!inflight) {
    inflight = getAccountFeatures()
      .then((f) => { cache = f; return f })
      .finally(() => { inflight = null })
  }
  return inflight
}

/** Clear the cached entitlements (call on sign-out / plan change). */
export function clearEntitlementsCache(): void {
  cache = null
  inflight = null
}

/**
 * Re-fetch entitlements and push the fresh payload to every mounted hook —
 * used after a business-type switch so terminology/modules update in place
 * (mounted components otherwise keep the stale cached payload).
 */
export async function refreshEntitlements(): Promise<void> {
  clearEntitlementsCache()
  const f = await load().catch(() => null)
  if (f) listeners.forEach((l) => l(f))
}

export interface Entitlements {
  features: AccountFeatures | null
  loading: boolean
  /** True if the module is enabled, or while still loading (permissive default). */
  hasModule: (m: ModuleKey) => boolean
  /** Monthly scored-lead allowance for metered plans; null = unlimited/unknown. */
  scoringQuota: ScoringQuota | null
}

export function useEntitlements(): Entitlements {
  const [features, setFeatures] = useState<AccountFeatures | null>(cache)
  const [loading, setLoading] = useState(!cache)

  useEffect(() => {
    let active = true
    const listener = (f: AccountFeatures) => { if (active) setFeatures(f) }
    listeners.add(listener)
    if (cache) { setFeatures(cache); setLoading(false) }
    else {
      load()
        .then((f) => { if (active) setFeatures(f) })
        .catch(() => { /* permissive: leave features null so hasModule returns true */ })
        .finally(() => { if (active) setLoading(false) })
    }
    return () => { active = false; listeners.delete(listener) }
  }, [])

  const hasModule = (m: ModuleKey): boolean => {
    if (!features) return true // not yet loaded / errored → don't hide
    return features.modules[m] !== false
  }

  return { features, loading, hasModule, scoringQuota: features?.scoring_quota ?? null }
}
