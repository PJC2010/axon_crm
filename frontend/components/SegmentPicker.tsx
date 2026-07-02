'use client'
import { useEffect, useState } from 'react'
import { Bookmark, BookmarkPlus, Trash2 } from 'lucide-react'
import { createSegment, deleteSegment, getSegments } from '@/lib/api'
import type { LeadFilters, Segment } from '@/lib/types'

// Filter keys a segment persists — pagination is ephemeral view state.
const SEGMENT_KEYS: (keyof LeadFilters)[] = [
  'zip', 'grade', 'vertical', 'status', 'min_value', 'max_value',
  'neighborhood', 'min_neighborhood_pctile', 'sort',
]

function segmentFilters(filters: LeadFilters): LeadFilters {
  const out: LeadFilters = {}
  for (const key of SEGMENT_KEYS) {
    const val = filters[key]
    if (val !== undefined && val !== null && val !== '') {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ;(out as any)[key] = val
    }
  }
  return out
}

export function SegmentPicker({ filters, onApply }: {
  filters: LeadFilters
  onApply: (filters: LeadFilters) => void
}) {
  const [segments, setSegments] = useState<Segment[]>([])
  const [selectedId, setSelectedId] = useState<number | ''>('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    getSegments().then(setSegments).catch(() => {})
  }, [])

  const hasFilters = Object.keys(segmentFilters(filters)).some(k => k !== 'sort')

  async function handleSave() {
    const name = window.prompt('Save current view as…')?.trim()
    if (!name) return
    setBusy(true)
    try {
      const created = await createSegment(name, segmentFilters(filters))
      setSegments(prev => [...prev.filter(s => s.id !== created.id), created]
        .sort((a, b) => a.name.localeCompare(b.name)))
      setSelectedId(created.id)
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Failed to save segment')
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete() {
    const segment = segments.find(s => s.id === selectedId)
    if (!segment || !confirm(`Delete saved view "${segment.name}"?`)) return
    setBusy(true)
    try {
      await deleteSegment(segment.id)
      setSegments(prev => prev.filter(s => s.id !== segment.id))
      setSelectedId('')
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Failed to delete segment')
    } finally {
      setBusy(false)
    }
  }

  if (segments.length === 0 && !hasFilters) return null

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <Bookmark size={13} strokeWidth={1.5} style={{ color: 'var(--color-ink-400)', flexShrink: 0 }} />
      <select
        value={selectedId}
        onChange={e => {
          const id = e.target.value ? Number(e.target.value) : ''
          setSelectedId(id)
          const segment = segments.find(s => s.id === id)
          if (segment) onApply({ ...segment.filters })
        }}
        className="drawer-input"
        style={{ fontSize: 12, maxWidth: 160 }}
        title="Saved views"
      >
        <option value="">Saved views…</option>
        {segments.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
      </select>
      {hasFilters && (
        <button
          onClick={handleSave}
          disabled={busy}
          className="dash-icon-btn"
          title="Save current view"
          style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}
        >
          <BookmarkPlus size={13} strokeWidth={1.5} />
        </button>
      )}
      {selectedId !== '' && (
        <button
          onClick={handleDelete}
          disabled={busy}
          className="dash-icon-btn"
          title="Delete saved view"
          style={{ padding: 4 }}
        >
          <Trash2 size={12} strokeWidth={1.5} />
        </button>
      )}
    </div>
  )
}
