'use client'
import { X, MapPin, Search } from 'lucide-react'
import type { CSSProperties, ReactNode } from 'react'
import { GRADE_TOKENS, type Grade } from '@/lib/gradeColors'
import { plural } from '@/lib/terminology'
import type { MapZip, CustomerSearchResult } from '@/lib/types'

function Hint({ children }: { children: ReactNode }) {
  return <div style={{ padding: '10px 4px', fontSize: 12, color: 'var(--color-ink-500)' }}>{children}</div>
}

/**
 * Jump control — a bottom sheet on mobile, a dropdown on desktop.
 *
 * Searches two things, both of them ours: the account's own ZIPs
 * (`GET /api/map/zips`, so every entry is guaranteed to contain leads and
 * picking one fits the map to that ZIP's real extent) and its leads
 * (`GET /api/leads/search`, which already ORs across account number, contact and
 * owner name, address, email and a digits-only phone match).
 *
 * **No geocoder, deliberately.** In a CRM "search" means *find my lead*, not
 * *find any address on Earth*, and reaching for `maplibre-gl-geocoder` or
 * Nominatim would answer the wrong question — while adding a second vendor,
 * leaking a key into the browser bundle, and bypassing the bounded, mostly-free
 * geocoding this app already does server-side (`pipeline/geocode.py`, which
 * exists because a serial paid loop once cost ~$200 on one ZIP). Nominatim's
 * public endpoint effectively prohibits this use anyway.
 *
 * The mobile affordances are deliberate and easy to regress: a full-width sheet
 * with 44px rows, `fontSize: 16` so iOS Safari doesn't auto-zoom the page on
 * focus, and a tap-anywhere backdrop. The input no longer forces a numeric
 * keypad — it did when this was ZIP-only, which would now make an address
 * untypeable.
 */
export function PlacePicker({
  zips, zipsLoading, query, onQuery, onPickZip,
  leads, leadsLoading, onPickLead,
  onClose, isMobile, areaLabel,
}: {
  zips: MapZip[]
  zipsLoading: boolean
  query: string
  onQuery: (v: string) => void
  onPickZip: (z: MapZip) => void
  leads: CustomerSearchResult[]
  leadsLoading: boolean
  onPickLead: (l: CustomerSearchResult) => void
  onClose: () => void
  isMobile: boolean
  areaLabel: string
}) {
  const term = query.trim()
  const digits = term.replace(/[^0-9]/g, '')
  // A ZIP match only makes sense for something that looks like a ZIP; otherwise
  // "1200 Main" would match ZIP 12000 and push the address hits down the list.
  const zipMatches = term
    ? (digits && digits === term ? zips.filter(z => z.zip.startsWith(digits)) : [])
    : zips

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
        width: 300, maxHeight: 420, display: 'flex', flexDirection: 'column',
        background: 'var(--color-paper)', border: '1px solid var(--color-ink-200)',
        borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)',
        padding: '10px 12px 12px',
      }

  const rowStyle: CSSProperties = {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    width: '100%', minHeight: 44, gap: 10, padding: '8px 10px', marginTop: 2,
    border: 'none', borderRadius: 'var(--radius-card)', background: 'transparent',
    cursor: 'pointer', textAlign: 'left',
  }

  const sectionStyle: CSSProperties = {
    fontSize: 10, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase',
    color: 'var(--color-ink-400)', padding: '8px 4px 2px',
  }

  const nothing = !zipMatches.length && !leads.length && !zipsLoading && !leadsLoading

  return (
    <>
      <div
        onClick={onClose}
        style={{
          position: 'absolute', inset: 0, zIndex: 5,
          background: isMobile ? 'rgba(0,0,0,0.28)' : 'transparent',
        }}
      />
      <div style={panel} role="dialog" aria-label="Jump to a ZIP code or lead">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-ink-900)' }}>Jump to</div>
            <div style={{ fontSize: 11, color: 'var(--color-ink-500)' }}>{areaLabel}</div>
          </div>
          <button onClick={onClose} className="dash-icon-btn borderless" title="Close" aria-label="Close">
            <X size={15} strokeWidth={1.5} />
          </button>
        </div>

        <input
          autoFocus={!isMobile}
          value={query}
          onChange={e => onQuery(e.target.value.slice(0, 60))}
          onKeyDown={e => {
            if (e.key !== 'Enter') return
            if (zipMatches.length) onPickZip(zipMatches[0])
            else if (leads.length) onPickLead(leads[0])
          }}
          placeholder="ZIP, address, or name…"
          enterKeyHint="go"
          aria-label="Search ZIP codes and leads"
          style={{
            width: '100%', padding: isMobile ? '11px 12px' : '8px 10px',
            fontSize: 16, borderRadius: 'var(--radius-pill)',
            border: '1px solid var(--color-ink-200)',
            background: 'var(--color-paper)', color: 'var(--color-ink-900)',
          }}
        />

        <div role="listbox" style={{ overflowY: 'auto', marginTop: 4, flex: 1 }}>
          {zipsLoading && !term && <Hint>Loading ZIP codes…</Hint>}
          {!zipsLoading && !zips.length && !term && <Hint>No mapped ZIP codes yet.</Hint>}

          {zipMatches.length > 0 && (
            <>
              <div style={sectionStyle}>ZIP codes</div>
              {zipMatches.map(z => (
                <button key={z.zip} role="option" aria-selected={false}
                  onClick={() => onPickZip(z)} style={rowStyle}>
                  <span style={{
                    display: 'flex', alignItems: 'center', gap: 8,
                    fontSize: 14, fontWeight: 600, color: 'var(--color-ink-900)',
                  }}>
                    <MapPin size={13} strokeWidth={1.5} /> {z.zip}
                  </span>
                  <span style={{ fontSize: 11, color: 'var(--color-ink-500)' }}>
                    {plural(z.leads, 'lead', 'leads')}
                  </span>
                </button>
              ))}
            </>
          )}

          {leadsLoading && <Hint>Searching leads…</Hint>}
          {leads.length > 0 && (
            <>
              <div style={sectionStyle}>Leads</div>
              {leads.map(l => {
                const g = (l.score_grade ?? '') as Grade
                const token = GRADE_TOKENS[g]
                const located = l.latitude != null && l.longitude != null
                return (
                  <button key={l.id} role="option" aria-selected={false}
                    onClick={() => onPickLead(l)} style={rowStyle}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0, flex: 1 }}>
                      <Search size={13} strokeWidth={1.5} style={{ flexShrink: 0 }} />
                      <span style={{ minWidth: 0 }}>
                        <span style={{
                          display: 'block', fontSize: 13, color: 'var(--color-ink-900)',
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        }}>
                          {l.address || l.contact_name || l.owner_name || l.account_number || `Lead ${l.id}`}
                        </span>
                        <span style={{ fontSize: 11, color: 'var(--color-ink-500)' }}>
                          {/* Say so rather than flying somewhere arbitrary: `properties` is
                              the contact book too, so a call-in lead has no coordinates. */}
                          {located ? (l.zip ?? '') : 'No map location'}
                        </span>
                      </span>
                    </span>
                    {token && (
                      <span style={{
                        fontSize: 10, fontWeight: 600, padding: '1px 6px', flexShrink: 0,
                        borderRadius: 'var(--radius-pill)', background: token.bg, color: token.fg,
                      }}>{g}</span>
                    )}
                  </button>
                )
              })}
            </>
          )}

          {term && nothing && <Hint>Nothing matches “{term}”.</Hint>}
        </div>
      </div>
    </>
  )
}
