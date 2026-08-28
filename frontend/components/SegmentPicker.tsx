'use client'
import { useEffect, useState } from 'react'
import { Bookmark, BookmarkPlus, Trash2, Check, X } from 'lucide-react'
import { createSegment, deleteSegment, getSegments } from '@/lib/api'
import { useConfirm } from '@/hooks/useConfirm'
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
  // Naming a view is inline rather than a window.prompt: the native dialog is
  // unstyled, blocks the tab, and drops what you typed if you mis-click.
  const [naming, setNaming] = useState(false)
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const { confirm, confirmDialog } = useConfirm()

  useEffect(() => {
    getSegments().then(setSegments).catch(() => {})
  }, [])

  const hasFilters = Object.keys(segmentFilters(filters)).some(k => k !== 'sort')

  async function handleSave() {
    const trimmed = name.trim()
    if (!trimmed) return
    setBusy(true); setError(null)
    try {
      const created = await createSegment(trimmed, segmentFilters(filters))
      setSegments(prev => [...prev.filter(s => s.id !== created.id), created]
        .sort((a, b) => a.name.localeCompare(b.name)))
      setSelectedId(created.id)
      setNaming(false); setName('')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "We couldn't save this view.")
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete() {
    const segment = segments.find(s => s.id === selectedId)
    if (!segment) return
    const ok = await confirm({
      title: `Delete “${segment.name}”?`,
      message: 'The saved view is removed. Your leads and filters are untouched.',
      confirmLabel: 'Delete view',
      danger: true,
    })
    if (!ok) return
    setBusy(true); setError(null)
    try {
      await deleteSegment(segment.id)
      setSegments(prev => prev.filter(s => s.id !== segment.id))
      setSelectedId('')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "We couldn't delete this view.")
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
      {hasFilters && !naming && (
        <button
          onClick={() => { setNaming(true); setError(null) }}
          disabled={busy}
          className="dash-icon-btn"
          title="Save current view"
          style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}
        >
          <BookmarkPlus size={13} strokeWidth={1.5} />
        </button>
      )}
      {hasFilters && naming && (
        <form
          onSubmit={e => { e.preventDefault(); handleSave() }}
          style={{ display: 'flex', alignItems: 'center', gap: 4 }}
        >
          <input
            autoFocus
            value={name}
            onChange={e => setName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Escape') { setNaming(false); setName(''); setError(null) } }}
            placeholder="Name this view"
            aria-label="Name this view"
            className="drawer-input"
            style={{ fontSize: 12, width: 140 }}
          />
          <button type="submit" disabled={busy || !name.trim()} className="dash-icon-btn" title="Save view" style={{ padding: 4 }}>
            <Check size={13} strokeWidth={1.75} />
          </button>
          <button
            type="button"
            onClick={() => { setNaming(false); setName(''); setError(null) }}
            className="dash-icon-btn"
            title="Cancel"
            style={{ padding: 4 }}
          >
            <X size={13} strokeWidth={1.75} />
          </button>
        </form>
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
      {error && (
        <span role="alert" style={{ fontSize: 12, color: 'var(--color-danger)' }}>{error}</span>
      )}
      {confirmDialog}
    </div>
  )
}
