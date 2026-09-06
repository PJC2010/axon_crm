'use client'
import Link from 'next/link'
import type { AdminDataHealth } from '@/lib/types'
import { TH_STYLE, TD_STYLE, zebra, fmtDateTime } from '../AdminTable'
import { dash, pctText } from '../Degraded'
import { CARD, pctOf } from './DataZipTable'

const H2: React.CSSProperties = { margin: 0, padding: '14px 16px 8px' }
const LINE: React.CSSProperties = {
  display: 'flex', justifyContent: 'space-between', gap: 8, padding: '7px 16px',
  borderBottom: '1px solid var(--color-ink-100)', fontSize: 12.5, color: 'var(--color-ink-800)',
}

/** The smaller panels: RentCast disagreements, the geocode queue, geocode
 *  sources and the mail-city tripwire. Every figure is "—" when its block
 *  did not compute. */
export function DataSideTables({ data }: { data: AdminDataHealth }) {
  const report = data.snapshot?.report
  const disc = report?.discrepancies ?? null
  const names = new Map(data.accounts.map((a) => [a.account_id, a.name]))
  const gq = data.live.geocode_queue
  const city = report?.city_sanity ?? null
  const hcad = report?.hcad ?? null

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 18 }}>
      <div style={{ ...CARD, marginBottom: 0 }}>
        <h2 className="t-eyebrow" style={H2}>RentCast disagreements · open</h2>
        <p style={{ margin: 0, padding: '0 16px 8px', fontSize: 12, color: 'var(--color-ink-400)', lineHeight: 1.5 }}>
          Fields where a paid lookup disagreed with the county and the stored value was kept (pipeline/reconcile.py). Counts only.
        </p>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead><tr><th style={TH_STYLE}>Field</th><th style={TH_STYLE}>Source</th><th style={TH_STYLE}>Open</th></tr></thead>
          <tbody>
            {(!disc || disc.by_field.length === 0) && (
              <tr><td colSpan={3} style={{ ...TD_STYLE, textAlign: 'center', padding: '16px 0', color: 'var(--color-ink-400)' }}>{disc ? 'None open' : '—'}</td></tr>
            )}
            {disc?.by_field.map((r, i) => (
              <tr key={`${r.field}-${r.source}`} style={{ background: zebra(i) }}>
                <td style={TD_STYLE}>{r.field}</td>
                <td style={TD_STYLE}>{r.source}</td>
                <td style={TD_STYLE} className="tabular">{r.open.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {disc && disc.by_account.length > 0 && (
          <div style={{ padding: '8px 0 6px' }}>
            <span className="t-eyebrow" style={{ display: 'block', padding: '0 16px 4px' }}>By organization</span>
            {disc.by_account.slice(0, 10).map((r) => (
              <div key={r.account_id} style={LINE}>
                <Link href={`/admin/orgs/${r.account_id}`} style={{ color: 'var(--color-ink-800)', textDecoration: 'none' }}>
                  {names.get(r.account_id) ?? `#${r.account_id}`}
                </Link>
                <span className="tabular">{r.open.toLocaleString()}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div style={{ ...CARD, marginBottom: 0 }}>
        <h2 className="t-eyebrow" style={H2}>Geocode queue · live</h2>
        <div style={LINE}><span>Queued</span><span className="tabular">{dash(gq?.queued)}</span></div>
        <div style={LINE}><span>Failed</span><span className="tabular" style={{ color: (gq?.failed ?? 0) > 0 ? 'var(--color-danger)' : undefined }}>{dash(gq?.failed)}</span></div>
        <div style={LINE}><span>Done</span><span className="tabular">{dash(gq?.done)}</span></div>
        <div style={LINE}><span>Oldest queued</span><span>{gq ? fmtDateTime(gq.oldest_queued_at) : '—'}</span></div>
        {gq && gq.top_errors.length > 0 && (
          <div style={{ padding: '8px 0 6px' }}>
            <span className="t-eyebrow" style={{ display: 'block', padding: '0 16px 4px' }}>Top failure reasons</span>
            {gq.top_errors.map((e, i) => (
              <div key={i} style={LINE}>
                <span style={{ color: 'var(--color-ink-600)', wordBreak: 'break-word' }}>{e.last_error ?? '(no message)'}</span>
                <span className="tabular">{e.n.toLocaleString()}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div style={{ ...CARD, marginBottom: 0 }}>
        <h2 className="t-eyebrow" style={H2}>Sources &amp; sanity</h2>
        {report?.geocode_sources?.map((s) => (
          <div key={s.source} style={LINE}><span>Coords from {s.source}</span><span className="tabular">{s.count.toLocaleString()}</span></div>
        ))}
        {!report?.geocode_sources && <div style={LINE}><span>Coordinate sources</span><span>—</span></div>}
        <div style={LINE}>
          <span title="County rows carrying the situs city (migration 0079)">HCAD mirror · site city filled</span>
          <span className="tabular">{hcad ? pctText(pctOf(hcad.site_city_filled, hcad.properties)) : '—'}</span>
        </div>
        <div style={LINE}>
          <span title="HCAD-seeded rows whose city is the owner's mailing city — must stay 0 (migration 0079)">Mail-city leak · parcels / leads</span>
          <span className="tabular" style={{ color: ((city?.parcels_mail_city_leak ?? 0) + (city?.properties_mail_city_leak ?? 0)) > 0 ? 'var(--color-danger)' : undefined }}>
            {dash(city?.parcels_mail_city_leak)} / {dash(city?.properties_mail_city_leak)}
          </span>
        </div>
        <div style={LINE}>
          <span title="HCAD-seeded rows still waiting for a situs city">NULL city · parcels / leads</span>
          <span className="tabular">{dash(city?.parcels_null_city)} / {dash(city?.properties_null_city)}</span>
        </div>
        <div style={LINE}>
          <span>Rule hashes · leads / parcels</span>
          <span className="tabular" style={{ fontSize: 11.5 }}>{data.rule.property_rule_hash} / {data.rule.parcel_rule_hash}</span>
        </div>
      </div>
    </div>
  )
}
