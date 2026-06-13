import type { Lead } from '@/lib/types'
import { VERTICAL_LABELS, fmt, fmtCurrency, fmtOccupied } from './format'

const SECTION_BORDER: React.CSSProperties = { borderBottom: '1px solid var(--color-ink-100)' }

/** Property facts grid — shared by the lead drawer and the full lead page. */
export function PropertySignals({ lead }: { lead: Lead }) {
  return (
    <section style={{ padding: '16px 24px', ...SECTION_BORDER }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <p className="t-eyebrow" style={{ margin: 0 }}>Property signals</p>
        {lead.vertical && (
          <span style={{
            fontSize: 10,
            fontWeight: 600,
            padding: '2px 8px',
            borderRadius: 'var(--radius-pill)',
            background: 'var(--color-accent-100)',
            color: 'var(--color-accent-800)',
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
          }}>
            {VERTICAL_LABELS[lead.vertical] ?? lead.vertical}
          </span>
        )}
      </div>
      <dl style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: 16, rowGap: 10 }}>
        {[
          ['Year built',     lead.year_built],
          ['Sq footage',     lead.square_footage ? `${lead.square_footage.toLocaleString()} sqft` : null],
          ['Garage spaces',  lead.garage_spaces],
          ['Owner occupied', fmtOccupied(lead.owner_occupied)],
          ['Est. value',     fmtCurrency(lead.estimated_value)],
          ['Est. equity',    fmtCurrency(lead.estimated_equity)],
          ['Last sale',      fmt(lead.last_sale_date)],
          ['Sale price',     fmtCurrency(lead.last_sale_price)],
          ['Area income',    fmtCurrency(lead.zip_median_income)],
          ['Permits (24mo)', lead.permit_count_24mo ?? '—'],
          ['Owner',          lead.owner_name],
          ['Neighborhood',   lead.hcad_neighborhood_name],
        ].map(([label, val]) => (
          <div key={String(label)}>
            <dt className="t-eyebrow" style={{ marginBottom: 2 }}>{label}</dt>
            <dd
              className="tabular"
              style={{ fontWeight: 500, color: 'var(--color-ink-900)', fontSize: 13, margin: 0 }}
            >
              {val ?? '—'}
            </dd>
          </div>
        ))}
      </dl>
      {lead.score_updated_at && (
        <p style={{ marginTop: 12, marginBottom: 0, fontSize: 11, color: 'var(--color-ink-400)' }}>
          Score updated {fmt(lead.score_updated_at)}
        </p>
      )}
    </section>
  )
}
