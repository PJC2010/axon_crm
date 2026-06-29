'use client'
import { useEffect, useState } from 'react'
import { SlidersHorizontal } from 'lucide-react'
import { getZips, getNeighborhoods } from '@/lib/api'
import { useTerminology } from '@/hooks/useTerminology'
import type { LeadFilters, Neighborhood } from '@/lib/types'

interface Props {
  filters: LeadFilters
  onChange: (f: LeadFilters) => void
}

const GRADES = ['A', 'B', 'C', 'D']

const GRADE_COLORS: Record<string, { active: React.CSSProperties; inactive: React.CSSProperties }> = {
  A: {
    active:   { background: 'var(--color-success-bg)', color: 'var(--color-success)',  borderColor: 'transparent' },
    inactive: { background: 'var(--color-paper)',      color: 'var(--color-ink-700)',   borderColor: 'var(--color-ink-200)' },
  },
  B: {
    active:   { background: 'var(--color-info-bg)',    color: 'var(--color-info)',      borderColor: 'transparent' },
    inactive: { background: 'var(--color-paper)',      color: 'var(--color-ink-700)',   borderColor: 'var(--color-ink-200)' },
  },
  C: {
    active:   { background: 'var(--color-warning-bg)', color: 'var(--color-warning)',   borderColor: 'transparent' },
    inactive: { background: 'var(--color-paper)',      color: 'var(--color-ink-700)',   borderColor: 'var(--color-ink-200)' },
  },
  D: {
    active:   { background: 'var(--color-danger-bg)',  color: 'var(--color-danger)',    borderColor: 'transparent' },
    inactive: { background: 'var(--color-paper)',      color: 'var(--color-ink-700)',   borderColor: 'var(--color-ink-200)' },
  },
}

const STATUSES = [
  { value: '',               label: 'All statuses' },
  { value: 'new',            label: 'New' },
  { value: 'contacted',      label: 'Contacted' },
  { value: 'qualified',      label: 'Qualified' },
  { value: 'not_interested', label: 'Not interested' },
  { value: 'converted',      label: 'Converted' },
]

const SORTS = [
  { value: 'score',               label: 'Score' },
  { value: 'sale_date',           label: 'Sale date' },
  { value: 'address',             label: 'Address' },
  { value: 'value',               label: 'Property value' },
  { value: 'neighborhood_pctile', label: 'Neighborhood value' },
]

// Preset property-value bands. Each sets min_value / max_value together.
const VALUE_BANDS = [
  { value: '',            label: 'Any value',     min: undefined, max: undefined },
  { value: '0-200000',    label: 'Under $200k',   min: undefined, max: 200_000 },
  { value: '200000-400000', label: '$200k–$400k', min: 200_000,   max: 400_000 },
  { value: '400000-600000', label: '$400k–$600k', min: 400_000,   max: 600_000 },
  { value: '600000-',     label: '$600k+',        min: 600_000,   max: undefined },
]

// "Top value within the block" — maps to the minimum neighborhood percentile.
const NEIGHBORHOOD_TIERS = [
  { value: '',    label: 'Any block rank' },
  { value: '0.9', label: 'Top 10% on block' },
  { value: '0.75', label: 'Top 25% on block' },
  { value: '0.5', label: 'Top 50% on block' },
]

function fmtValue(v: number | null): string {
  if (v == null) return '—'
  return v >= 1_000_000 ? `$${(v / 1_000_000).toFixed(1)}M` : `$${Math.round(v / 1000)}k`
}

export function TerritoryFilter({ filters, onChange }: Props) {
  const { t, categories } = useTerminology()
  const verticalOptions = [{ value: '', label: `All ${t('categories').toLowerCase()}` }, ...categories]
  const [zips, setZips] = useState<string[]>([])
  const [neighborhoods, setNeighborhoods] = useState<Neighborhood[]>([])

  useEffect(() => {
    getZips().then(setZips).catch(() => {})
  }, [])

  // Neighborhood options narrow with the selected ZIP. Clear any stale
  // neighborhood selection when the ZIP changes.
  useEffect(() => {
    getNeighborhoods(filters.zip).then(setNeighborhoods).catch(() => setNeighborhoods([]))
  }, [filters.zip])

  function set(key: keyof LeadFilters, val: string) {
    onChange({ ...filters, [key]: val || undefined, page: 1 })
  }

  function setNum(key: keyof LeadFilters, val: string) {
    onChange({ ...filters, [key]: val ? Number(val) : undefined, page: 1 })
  }

  function setBand(val: string) {
    const band = VALUE_BANDS.find(b => b.value === val)
    onChange({ ...filters, min_value: band?.min, max_value: band?.max, page: 1 })
  }

  const currentBand =
    VALUE_BANDS.find(b => b.min === filters.min_value && b.max === filters.max_value)?.value ?? ''

  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        gap: 10,
        padding: '10px 20px',
        background: 'var(--color-paper)',
        borderBottom: '1px solid var(--color-ink-200)',
      }}
    >
      <SlidersHorizontal
        size={14}
        strokeWidth={1.5}
        style={{ color: 'var(--color-ink-400)', flexShrink: 0 }}
      />

      {/* ZIP */}
      <select value={filters.zip ?? ''} onChange={e => set('zip', e.target.value)} className="select-field">
        <option value="">All ZIPs</option>
        {zips.map(z => <option key={z} value={z}>{z}</option>)}
      </select>

      {/* Category (vertical) */}
      <select value={filters.vertical ?? ''} onChange={e => set('vertical', e.target.value)} className="select-field">
        {verticalOptions.map(v => <option key={v.value} value={v.value}>{v.label}</option>)}
      </select>

      {/* Grade chips — color-coded to match ScoreBadge palette */}
      <div style={{ display: 'flex', gap: 5 }}>
        {GRADES.map(g => {
          const active = filters.grade === g
          const colors = active ? GRADE_COLORS[g].active : GRADE_COLORS[g].inactive
          return (
            <button
              key={g}
              onClick={() => set('grade', active ? '' : g)}
              style={{
                padding: '4px 11px',
                borderRadius: 'var(--radius-pill)',
                fontSize: 12,
                fontWeight: 600,
                border: `1px solid ${colors.borderColor}`,
                background: colors.background,
                color: colors.color,
                cursor: 'pointer',
                transition: 'background 150ms, border-color 150ms, color 150ms',
                lineHeight: 1,
                letterSpacing: '0.03em',
              }}
            >
              {g}
            </button>
          )
        })}
      </div>

      {/* Status */}
      <select value={filters.status ?? ''} onChange={e => set('status', e.target.value)} className="select-field">
        {STATUSES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
      </select>

      {/* Neighborhood (geohash-6 block) — narrows with the selected ZIP */}
      <select value={filters.neighborhood ?? ''} onChange={e => set('neighborhood', e.target.value)} className="select-field">
        <option value="">All neighborhoods</option>
        {neighborhoods.map(n => (
          <option key={n.cell} value={n.cell}>
            {(n.name ?? n.cell)} · {fmtValue(n.median_value)} med · {n.leads} leads
          </option>
        ))}
      </select>

      {/* Property-value band */}
      <select value={currentBand} onChange={e => setBand(e.target.value)} className="select-field">
        {VALUE_BANDS.map(b => <option key={b.value} value={b.value}>{b.label}</option>)}
      </select>

      {/* Top value within the block */}
      <select
        value={filters.min_neighborhood_pctile != null ? String(filters.min_neighborhood_pctile) : ''}
        onChange={e => setNum('min_neighborhood_pctile', e.target.value)}
        className="select-field"
      >
        {NEIGHBORHOOD_TIERS.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
      </select>

      {/* Sort — pushed to right */}
      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 12, color: 'var(--color-ink-500)' }}>Sort by</span>
        <select value={filters.sort ?? 'score'} onChange={e => set('sort', e.target.value)} className="select-field">
          {SORTS.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
      </div>
    </div>
  )
}
