'use client'
import { useEffect, useState } from 'react'
import { SlidersHorizontal } from 'lucide-react'
import { getZips } from '@/lib/api'
import type { LeadFilters } from '@/lib/types'

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

const VERTICALS = [
  { value: '',                 label: 'All verticals' },
  { value: 'epoxy_flooring',   label: 'Epoxy flooring' },
  { value: 'pool_maintenance', label: 'Pool maintenance' },
  { value: 'solar',            label: 'Solar' },
  { value: 'roofing',          label: 'Roofing' },
  { value: 'hvac',             label: 'HVAC' },
  { value: 'fencing',          label: 'Fencing' },
  { value: 'landscaping',      label: 'Landscaping' },
  { value: 'pressure_washing', label: 'Pressure washing' },
]

const SORTS = [
  { value: 'score',     label: 'Score' },
  { value: 'sale_date', label: 'Sale date' },
  { value: 'address',   label: 'Address' },
]

export function TerritoryFilter({ filters, onChange }: Props) {
  const [zips, setZips] = useState<string[]>([])

  useEffect(() => {
    getZips().then(setZips).catch(() => {})
  }, [])

  function set(key: keyof LeadFilters, val: string) {
    onChange({ ...filters, [key]: val || undefined, page: 1 })
  }

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

      {/* Vertical */}
      <select value={filters.vertical ?? ''} onChange={e => set('vertical', e.target.value)} className="select-field">
        {VERTICALS.map(v => <option key={v.value} value={v.value}>{v.label}</option>)}
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
