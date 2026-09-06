'use client'
import Link from 'next/link'
import type { DataHealthAccountRow } from '@/lib/types'
import { TH_STYLE, TD_STYLE, zebra, fmtDate } from '../AdminTable'
import { dash, pctText } from '../Degraded'
import { CARD, RuleTag, pctOf } from './DataZipTable'

/** Each org's book: coordinates, classification backlog (from the snapshot
 *  and live), excludable rows, and whether its verdicts match the deployed
 *  rule. An org created since the snapshot shows "—" for the counts. */
export function DataAccountsTable({ accounts }: { accounts: DataHealthAccountRow[] }) {
  return (
    <div style={CARD}>
      <h2 className="t-eyebrow" style={{ margin: 0, padding: '14px 16px 8px' }}>Leads by organization</h2>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={TH_STYLE}>Org</th>
            <th style={TH_STYLE} title="Live leads at the snapshot">Leads</th>
            <th style={TH_STYLE} title="Leads with coordinates">Coords</th>
            <th style={TH_STYLE} title="No residential verdict at the snapshot">Unclassified</th>
            <th style={TH_STYLE} title="No residential verdict right now (index-only read)">Unclassified · live</th>
            <th style={TH_STYLE} title="Leads the rule marks as not a home">Excludable</th>
            <th style={TH_STYLE} title="Whether the org's verdicts were derived under the rule as deployed">Rule</th>
            <th style={TH_STYLE}>Classified</th>
          </tr>
        </thead>
        <tbody>
          {accounts.length === 0 && (
            <tr><td colSpan={8} style={{ ...TD_STYLE, textAlign: 'center', padding: '24px 0', color: 'var(--color-ink-400)' }}>No organizations</td></tr>
          )}
          {accounts.map((a, i) => (
            <tr key={a.account_id} style={{ background: zebra(i) }}>
              <td style={TD_STYLE}>
                <Link href={`/admin/orgs/${a.account_id}`} style={{ fontWeight: 600, color: 'var(--color-ink-900)', textDecoration: 'none' }}>{a.name}</Link>
                <span style={{ color: 'var(--color-ink-400)', marginLeft: 6, fontSize: 12 }}>#{a.account_id}</span>
              </td>
              <td style={TD_STYLE} className="tabular">{dash(a.properties)}</td>
              <td style={TD_STYLE} className="tabular">{pctText(pctOf(a.with_coords, a.properties))}</td>
              <td style={TD_STYLE} className="tabular">{dash(a.unclassified)}</td>
              <td style={{ ...TD_STYLE, color: (a.unclassified_live ?? 0) > 0 ? 'var(--color-warning)' : TD_STYLE.color }} className="tabular">{dash(a.unclassified_live)}</td>
              <td style={TD_STYLE} className="tabular">{dash(a.excludable)}</td>
              <td style={TD_STYLE}><RuleTag state={a.rule_state} /></td>
              <td style={TD_STYLE}>{fmtDate(a.classified_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
