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
const STATUSES = [
  { value: '',               label: 'All statuses' },
  { value: 'new',            label: 'New' },
  { value: 'contacted',      label: 'Contacted' },
  { value: 'qualified',      label: 'Qualified' },
  { value: 'not_interested', label: 'Not interested' },
  { value: 'converted',      label: 'Converted' },
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
        gap: 12,
        padding: '10px 20px',
        background: 'white',
        borderBottom: '1px solid var(--color-ink-200)',
      }}
    >
      <SlidersHorizontal size={15} strokeWidth={1.5} style={{ color: 'var(--color-ink-400)', flexShrink: 0 }} />

      <select value={filters.zip ?? ''} onChange={e => set('zip', e.target.value)} className="select-field">
        <option value="">All ZIPs</option>
        {zips.map(z => <option key={z} value={z}>{z}</option>)}
      </select>

      {/* Grade filter chips — toggle pattern from design system */}
      <div style={{ display: 'flex', gap: 6 }}>
        {GRADES.map(g => {
          const active = filters.grade === g
          return (
            <button
              key={g}
              onClick={() => set('grade', active ? '' : g)}
              style={{
                padding: '5px 12px',
                borderRadius: 9999,
                fontSize: 13,
                fontWeight: 500,
                border: `1px solid ${active ? 'var(--color-ink-900)' : 'var(--color-ink-200)'}`,
                background: active ? 'var(--color-ink-900)' : 'var(--color-paper)',
                color: active ? 'var(--color-cream)' : 'var(--color-ink-800)',
                cursor: 'pointer',
                transition: 'background 150ms, border-color 150ms, color 150ms',
                lineHeight: 1,
              }}
            >
              {g}
            </button>
          )
        })}
      </div>

      <select value={filters.status ?? ''} onChange={e => set('status', e.target.value)} className="select-field">
        {STATUSES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
      </select>

      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--color-ink-500)' }}>
        <span>Sort by</span>
        <select value={filters.sort ?? 'score'} onChange={e => set('sort', e.target.value)} className="select-field">
          {SORTS.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
      </div>
    </div>
  )
}
