// Shared formatting helpers + labels for the lead drawer and the full lead page.

export const VERTICAL_LABELS: Record<string, string> = {
  epoxy_flooring:   'Epoxy flooring',
  pool_maintenance: 'Pool maintenance',
  solar:            'Solar',
}

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
