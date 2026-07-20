import { Home, Lock, User } from 'lucide-react'
import type { Category, Lead, LeadStatus } from '@/lib/types'
import { ScoreBadge } from '../ScoreBadge'
import { StatusSelect } from '../StatusSelect'
import { VERTICAL_LABELS } from './format'

/**
 * Lead-list column registry. The backend business-type preset
 * (api/business_types.py `list_columns`) picks an ordered set of these keys per
 * vertical; LeadTable resolves them here so property columns disappear for
 * non-property businesses (insurance, retail, …). Every column reads only fields
 * already on the lead row — no policy/order join.
 *
 * Formatting matches the table's historical style (compact currency, month/year
 * dates) so the home-services layout is unchanged.
 */

// Compact table formatters (kept local so property columns render identically to
// the pre-registry table — $120K / "Jun 2024", not the fuller lead/format.ts forms).
function fmtMonthYear(d: string | null): string {
  if (!d) return '—'
  return new Date(d).toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
}
function fmtCompactCurrency(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`
  return `$${n}`
}

export interface LeadColumnContext {
  t: (key: string) => string
  categories: Category[]
  propertyBased: boolean
}

export interface LeadColumnHandlers {
  onStatusChange: (id: number, s: LeadStatus) => void
}

export interface LeadColumn {
  key: string
  header: string
  /** Extra <td> style merged over the table's base cell style. */
  cellStyle?: React.CSSProperties
  cellClassName?: string
  /** Interactive cells (status) stop row-click propagation. */
  stopPropagation?: boolean
  render: (lead: Lead, handlers: LeadColumnHandlers) => React.ReactNode
}

const NUMERIC_CELL: React.CSSProperties = { whiteSpace: 'nowrap' }

/** The vertical/category label for a lead, preferring the account's live picklist. */
function categoryLabel(lead: Lead, ctx: LeadColumnContext): string | null {
  if (!lead.vertical) return null
  const match = ctx.categories.find((c) => c.value === lead.vertical)
  return match?.label ?? VERTICAL_LABELS[lead.vertical] ?? lead.vertical
}

function CategoryPill({ label }: { label: string }) {
  return (
    <span style={{
      fontSize: 10,
      fontWeight: 600,
      padding: '2px 8px',
      borderRadius: 'var(--radius-pill)',
      background: 'var(--color-accent-100)',
      color: 'var(--color-accent-300)',
      textTransform: 'uppercase',
      letterSpacing: '0.05em',
      whiteSpace: 'nowrap',
    }}>
      {label}
    </span>
  )
}

/** Build the full registry bound to the current account's terminology context. */
function buildRegistry(ctx: LeadColumnContext): Record<string, LeadColumn> {
  const { t, propertyBased } = ctx
  return {
    record: {
      key: 'record',
      header: propertyBased ? 'Address' : t('record'),
      cellStyle: { maxWidth: 240 },
      render: (lead) => {
        // Quota-masked rows (api/scoring_quota.py) arrive with the address
        // partially hidden server-side; the lock marks why.
        const Icon = lead.quota_masked ? Lock : propertyBased ? Home : User
        const primary = propertyBased
          ? (lead.address || lead.contact_name || '—')
          : (lead.contact_name || lead.owner_name || lead.address || '—')
        const secondary = lead.quota_masked
          ? 'Past this month’s scored-lead allowance'
          : propertyBased
            ? [lead.city, lead.state, lead.zip].filter(Boolean).join(', ')
            : ([lead.city, lead.state].filter(Boolean).join(', ') || lead.account_number || '')
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, opacity: lead.quota_masked ? 0.65 : 1 }}>
            <Icon size={13} strokeWidth={1.5} style={{ color: 'var(--color-ink-300)', flexShrink: 0 }} />
            <div style={{ minWidth: 0 }}>
              <p style={{ fontWeight: 500, color: 'var(--color-ink-900)', fontSize: 13.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {primary}
              </p>
              {secondary && (
                <p style={{ fontSize: 11, color: 'var(--color-ink-500)', marginTop: 1 }}>{secondary}</p>
              )}
            </div>
          </div>
        )
      },
    },
    score: {
      key: 'score',
      header: 'Score',
      cellStyle: NUMERIC_CELL,
      render: (lead) => <ScoreBadge grade={lead.score_grade} score={lead.lead_score} />,
    },
    status: {
      key: 'status',
      header: 'Status',
      stopPropagation: true,
      render: (lead, { onStatusChange }) => (
        <StatusSelect leadId={lead.id} value={lead.status} onChange={(s) => onStatusChange(lead.id, s)} />
      ),
    },
    category: {
      key: 'category',
      header: t('category'),
      render: (lead) => {
        const label = categoryLabel(lead, ctx)
        return label ? <CategoryPill label={label} /> : <span style={{ color: 'var(--color-ink-300)' }}>—</span>
      },
    },
    job_value: {
      key: 'job_value',
      header: t('jobValue'),
      cellClassName: 'tabular',
      cellStyle: NUMERIC_CELL,
      render: (lead) => fmtCompactCurrency(lead.estimated_job_value),
    },
    x_date: {
      key: 'x_date',
      header: 'X-date',
      cellClassName: 'tabular',
      cellStyle: NUMERIC_CELL,
      render: (lead) => {
        const raw = lead.custom_fields?.['x_date']
        return fmtMonthYear(typeof raw === 'string' ? raw : null)
      },
    },
    // ── Property columns (home-services default) ──────────────────────────────
    year_built: {
      key: 'year_built',
      header: 'Year built',
      cellClassName: 'tabular',
      render: (lead) => lead.year_built ?? '—',
    },
    equity: {
      key: 'equity',
      header: 'Equity',
      cellClassName: 'tabular',
      render: (lead) => fmtCompactCurrency(lead.estimated_equity),
    },
    garage: {
      key: 'garage',
      header: 'Garage',
      cellClassName: 'tabular',
      render: (lead) => (lead.garage_spaces != null ? `${lead.garage_spaces}-car` : '—'),
    },
    last_sale: {
      key: 'last_sale',
      header: 'Last sale',
      cellClassName: 'tabular',
      cellStyle: NUMERIC_CELL,
      render: (lead) => fmtMonthYear(lead.last_sale_date),
    },
  }
}

/** Resolve an ordered list of column keys to column defs, skipping unknown keys. */
export function resolveLeadColumns(keys: string[], ctx: LeadColumnContext): LeadColumn[] {
  const registry = buildRegistry(ctx)
  return keys.map((k) => registry[k]).filter((c): c is LeadColumn => Boolean(c))
}
