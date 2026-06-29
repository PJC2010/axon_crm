'use client'
import { useEffect, useState } from 'react'
import { getAccountFeatures } from '@/lib/api'
import type { AccountFeatures, ModuleKey } from '@/lib/types'

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

function load(): Promise<AccountFeatures> {
  if (cache) return Promise.resolve(cache)
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

export interface Entitlements {
  features: AccountFeatures | null
  loading: boolean
  /** True if the module is enabled, or while still loading (permissive default). */
  hasModule: (m: ModuleKey) => boolean
}

export function useEntitlements(): Entitlements {
  const [features, setFeatures] = useState<AccountFeatures | null>(cache)
  const [loading, setLoading] = useState(!cache)

  useEffect(() => {
    let active = true
    if (cache) { setFeatures(cache); setLoading(false); return }
    load()
      .then((f) => { if (active) setFeatures(f) })
      .catch(() => { /* permissive: leave features null so hasModule returns true */ })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  const hasModule = (m: ModuleKey): boolean => {
    if (!features) return true // not yet loaded / errored → don't hide
    return features.modules[m] !== false
  }

  return { features, loading, hasModule }
}
