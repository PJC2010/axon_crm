// Shared formatting helpers + labels for the lead drawer and the full lead page.
import { DEFAULT_CATEGORIES } from '@/lib/terminology'

// Default (home-services) category labels, derived from the single source in
// terminology.ts. For non-home-services business types, prefer the live
// categories from useTerminology(); this map is the fallback for unknown values.
export const VERTICAL_LABELS: Record<string, string> = Object.fromEntries(
  DEFAULT_CATEGORIES.map((c) => [c.value, c.label]),
)

export function fmt(d: string | null) {
  if (!d) return '—'
  return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export function fmtCurrency(n: number | null) {
  if (!n) return '—'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n)
}

export function fmtOccupied(v: boolean | null) {
  if (v === null || v === undefined) return '—'
  return v ? 'Yes' : 'No'
}
