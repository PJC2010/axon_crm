'use client'
import { useState } from 'react'
import type { DataHealthZip, RuleState } from '@/lib/types'
import { Tag } from '@/components/ds'
import { TH_STYLE, TD_STYLE, zebra, fmtDate } from '../AdminTable'
import { pctText } from '../Degraded'

export const CARD: React.CSSProperties = {
  background: 'var(--color-surface)', borderRadius: 'var(--radius-card)',
  boxShadow: 'var(--shadow-card)', marginBottom: 18, overflowX: 'auto',
}

const RULE_INTENT: Record<RuleState, 'success' | 'warning' | 'none'> = {
  current: 'success', stale: 'warning', unstamped: 'none',
}

export function RuleTag({ state }: { state: RuleState }) {
  return <Tag intent={RULE_INTENT[state]}>{state}</Tag>
}

export function pctOf(n: number | null, d: number | null): number | null {
  if (n === null || d === null || !d) return null
  return (100 * n) / d
}

const SHOW = 40

/** Parcel-cache coverage per ZIP, biggest cache first. Coverage compares the
 *  cache with the county roll's own row count for the ZIP, so a ZIP the roll
 *  knows and the cache does not reads 0%, not missing. */
export function DataZipTable({ zips }: { zips: DataHealthZip[] }) {
  const [filter, setFilter] = useState('')
  const [showAll, setShowAll] = useState(false)
  const filtered = zips.filter((z) => z.zip.startsWith(filter.trim()))
  const shown = showAll ? filtered : filtered.slice(0, SHOW)

  return (
    <div style={CARD}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 16px 8px', flexWrap: 'wrap' }}>
        <h2 className="t-eyebrow" style={{ margin: 0 }}>Parcel cache by ZIP</h2>
        <input className="drawer-input" value={filter} onChange={(e) => { setFilter(e.target.value); setShowAll(false) }} placeholder="Filter ZIP" style={{ width: 120, marginLeft: 'auto' }} />
        <span style={{ fontSize: 12, color: 'var(--color-ink-400)' }}>{filtered.length.toLocaleString()} ZIPs</span>
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={TH_STYLE}>ZIP</th>
            <th style={TH_STYLE} title="Rows in the county roll (hcad_properties)">County rows</th>
            <th style={TH_STYLE} title="Rows in the shared parcel cache">Cached</th>
            <th style={TH_STYLE} title="Cached ÷ county rows">Coverage</th>
            <th style={TH_STYLE} title="Cached parcels with coordinates">Coords</th>
            <th style={TH_STYLE} title="Cached parcels with no residential verdict yet">Unclassified</th>
            <th style={TH_STYLE} title="Cached parcels the rule excludes (not a home)">Non-res</th>
            <th style={TH_STYLE} title="Whether the ZIP's verdicts were derived under the rule as deployed">Rule</th>
            <th style={TH_STYLE}>Classified</th>
          </tr>
        </thead>
        <tbody>
          {zips.length === 0 && (
            <tr><td colSpan={9} style={{ ...TD_STYLE, textAlign: 'center', padding: '24px 0', color: 'var(--color-ink-400)' }}>No snapshot yet</td></tr>
          )}
          {shown.map((z, i) => (
            <tr key={z.zip} style={{ background: zebra(i) }}>
              <td style={TD_STYLE} className="tabular">{z.zip}</td>
              <td style={TD_STYLE} className="tabular">{z.hcad_rows.toLocaleString()}</td>
              <td style={TD_STYLE} className="tabular">{z.parcels.toLocaleString()}</td>
              <td style={TD_STYLE} className="tabular">{pctText(pctOf(z.parcels, z.hcad_rows))}</td>
              <td style={TD_STYLE} className="tabular">{pctText(pctOf(z.with_coords, z.parcels))}</td>
              <td style={{ ...TD_STYLE, color: z.unclassified > 0 ? 'var(--color-warning)' : TD_STYLE.color }} className="tabular">{z.unclassified.toLocaleString()}</td>
              <td style={TD_STYLE} className="tabular">{pctText(pctOf(z.non_residential, z.parcels))}</td>
              <td style={TD_STYLE}><RuleTag state={z.rule_state} /></td>
              <td style={TD_STYLE}>{fmtDate(z.classified_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {filtered.length > shown.length && (
        <div style={{ padding: '8px 16px 14px' }}>
          <button className="btn-secondary" style={{ fontSize: 12.5 }} onClick={() => setShowAll(true)}>
            Show all {filtered.length.toLocaleString()}
          </button>
        </div>
      )}
    </div>
  )
}
