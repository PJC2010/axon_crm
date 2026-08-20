'use client'
import { X } from 'lucide-react'
import type { CSSProperties, ReactNode } from 'react'
import type { MapZip } from '@/lib/types'

function ZipHint({ children }: { children: ReactNode }) {
  return <div style={{ padding: '10px 4px', fontSize: 12, color: 'var(--color-ink-500)' }}>{children}</div>
}

/**
 * ZIP jump control — a bottom sheet on mobile, a dropdown on desktop.
 *
 * The list is the account's *own* ZIPs (`GET /api/map/zips`), so every entry is
 * guaranteed to contain leads and picking one fits the map to that ZIP's real
 * extent. That's why there's no geocoder here: "find my territory" is a
 * different question from "find any place on Earth", and the answer is already
 * in our own data.
 *
 * The mobile affordances are deliberate and easy to regress: a full-width sheet
 * with 44px rows, `inputMode="numeric"` for the keypad, `fontSize: 16` so iOS
 * Safari doesn't auto-zoom the page on focus, and a tap-anywhere backdrop.
 */
export function ZipPicker({
  zips, loading, query, onQuery, onPick, onClose, isMobile, areaLabel,
}: {
  zips: MapZip[]
  loading: boolean
  query: string
  onQuery: (v: string) => void
  onPick: (z: MapZip) => void
  onClose: () => void
  isMobile: boolean
  areaLabel: string
}) {
  const term = query.trim()
  const filtered = term ? zips.filter(z => z.zip.startsWith(term)) : zips

  const panel: CSSProperties = isMobile
    ? {
        position: 'absolute', left: 0, right: 0, bottom: 0, zIndex: 6,
        maxHeight: '62%', display: 'flex', flexDirection: 'column',
        background: 'var(--color-paper)', borderTop: '1px solid var(--color-ink-200)',
        borderTopLeftRadius: 16, borderTopRightRadius: 16,
        boxShadow: 'var(--shadow-card)', padding: '10px 12px 14px',
      }
    : {
        position: 'absolute', top: 12, left: 16, zIndex: 6,
        width: 280, maxHeight: 380, display: 'flex', flexDirection: 'column',
        background: 'var(--color-paper)', border: '1px solid var(--color-ink-200)',
        borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)',
        padding: '10px 12px 12px',
      }

  return (
    <>
      <div
        onClick={onClose}
        style={{
          position: 'absolute', inset: 0, zIndex: 5,
          background: isMobile ? 'rgba(0,0,0,0.28)' : 'transparent',
        }}
      />
      <div style={panel} role="dialog" aria-label="Jump to a ZIP code">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-ink-900)' }}>Jump to ZIP</div>
            <div style={{ fontSize: 11, color: 'var(--color-ink-500)' }}>{areaLabel}</div>
          </div>
          <button onClick={onClose} className="dash-icon-btn borderless" title="Close" aria-label="Close">
            <X size={15} strokeWidth={1.5} />
          </button>
        </div>

        <input
          autoFocus={!isMobile}
          value={query}
          onChange={e => onQuery(e.target.value.replace(/[^0-9]/g, '').slice(0, 5))}
          onKeyDown={e => { if (e.key === 'Enter' && filtered.length) onPick(filtered[0]) }}
          placeholder="Search ZIP…"
          inputMode="numeric"
          enterKeyHint="go"
          aria-label="Filter ZIP codes"
          style={{
            width: '100%', padding: isMobile ? '11px 12px' : '8px 10px',
            fontSize: 16, borderRadius: 'var(--radius-pill)',
            border: '1px solid var(--color-ink-200)',
            background: 'var(--color-paper)', color: 'var(--color-ink-900)',
          }}
        />

        <div role="listbox" style={{ overflowY: 'auto', marginTop: 8, flex: 1 }}>
          {loading && <ZipHint>Loading ZIP codes…</ZipHint>}
          {!loading && !zips.length && <ZipHint>No mapped ZIP codes yet.</ZipHint>}
          {!loading && zips.length > 0 && !filtered.length && (
            <ZipHint>No ZIP starts with “{term}”.</ZipHint>
          )}
          {!loading && filtered.map(z => (
            <button
              key={z.zip}
              role="option"
              aria-selected={false}
              onClick={() => onPick(z)}
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                width: '100%', minHeight: 44, gap: 10, padding: '8px 10px', marginTop: 2,
                border: 'none', borderRadius: 'var(--radius-card)', background: 'transparent',
                cursor: 'pointer', textAlign: 'left',
              }}
            >
              <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-ink-900)' }}>{z.zip}</span>
              <span style={{ fontSize: 11, color: 'var(--color-ink-500)' }}>
                {z.leads.toLocaleString()} lead{z.leads === 1 ? '' : 's'}
              </span>
            </button>
          ))}
        </div>
      </div>
    </>
  )
}
