'use client'
import { useMemo } from 'react'
import { useEntitlements } from './useEntitlements'
import { makeT, DEFAULT_CATEGORIES } from '@/lib/terminology'
import type { Category } from '@/lib/types'

/**
 * Business-type terminology + categories for the current account.
 *
 * Reuses the cached account-features fetch from useEntitlements (one request per
 * page), then derives: `t(key)` for terminology (with home-services defaults as
 * fallback), the `categories` picklist that replaces hardcoded vertical lists,
 * and `propertyBased` for hiding property-specific UI. All have permissive
 * defaults so the UI renders sensibly before the profile loads.
 */
export interface Terminology {
  t: (key: string) => string
  categories: Category[]
  propertyBased: boolean
  businessType: string
  // Dashboard KPI tile ids for this business type (Phase 6 packs); the default
  // reproduces the classic four home-services tiles.
  kpis: string[]
}

const DEFAULT_KPIS = ['revenue_mtd', 'outstanding_ar', 'win_rate', 'forecast']

export function useTerminology(): Terminology {
  const { features } = useEntitlements()

  return useMemo(() => ({
    t: makeT(features?.terminology),
    categories: features?.categories ?? DEFAULT_CATEGORIES,
    propertyBased: features?.property_based ?? true,
    businessType: features?.business_type ?? 'home_services',
    kpis: features?.kpis ?? DEFAULT_KPIS,
  }), [features])
}
