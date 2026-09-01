'use client'
import Link from 'next/link'
import { Lock } from 'lucide-react'

// What the blur sits over: a facsimile of the property-signals grid with
// FAKE values. The real fields never render for a masked lead — the blur is
// the look, the placeholder data is the guarantee (devtools shows nothing).
const FACSIMILE_ROWS: Array<[string, string]> = [
  ['Year built', '1987'],
  ['Sq footage', '2,140 sqft'],
  ['Garage spaces', '2'],
  ['Owner occupied', 'No'],
  ['Est. value', '$418K'],
  ['Est. equity', '$236K'],
  ['Last sale', 'Jun 2014'],
  ['Sale price', '$291K'],
  ['Area income', '$74K'],
  ['Permits (24mo)', '1'],
  ['Owner', 'Firstname Lastname'],
  ['Neighborhood', 'Placeholder Park'],
]

/**
 * Replacement body for a quota-masked lead's detail view (drawer and full
 * page): a gaussian-blurred placeholder of the property facts with a lock
 * overlay and the upgrade path. Rendered INSTEAD of the live sections — a
 * masked lead must not mount the data sections at all, both so nothing real
 * sits under the blur and so their per-lead fetches never fire.
 */
export function MaskedLeadPanel() {
  return (
    <div style={{ position: 'relative', overflow: 'hidden', minHeight: 380 }}>
      {/* Blurred facsimile — decorative only. */}
      <div
        aria-hidden
        style={{
          filter: 'blur(7px)',
          userSelect: 'none',
          pointerEvents: 'none',
          padding: '16px 24px',
        }}
      >
        <p className="t-eyebrow" style={{ margin: '0 0 12px' }}>Property signals</p>
        <dl style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: 16, rowGap: 14, margin: 0 }}>
          {FACSIMILE_ROWS.map(([label, val]) => (
            <div key={label}>
              <dt className="t-eyebrow" style={{ marginBottom: 2 }}>{label}</dt>
              <dd className="tabular" style={{ fontWeight: 500, color: 'var(--color-ink-900)', fontSize: 14, margin: 0 }}>
                {val}
              </dd>
            </div>
          ))}
        </dl>
        <p className="t-eyebrow" style={{ margin: '20px 0 10px' }}>Contact</p>
        {['(555) 014-2907', 'name@example.com', '1234 Sample St, Houston, TX'].map(line => (
          <p key={line} style={{ fontSize: 14, fontWeight: 500, color: 'var(--color-ink-900)', margin: '0 0 8px' }}>
            {line}
          </p>
        ))}
      </div>

      {/* Lock overlay */}
      <div
        style={{
          position: 'absolute', inset: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          padding: 24,
        }}
      >
        <div
          style={{
            maxWidth: 300, textAlign: 'center',
            background: 'var(--color-surface)',
            border: '1px solid var(--color-ink-200)',
            borderRadius: 'var(--radius-card)',
            boxShadow: 'var(--shadow-drawer)',
            padding: '24px 22px',
          }}
        >
          <div
            style={{
              width: 40, height: 40, borderRadius: '50%',
              background: 'var(--color-ink-100)',
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              marginBottom: 12,
            }}
          >
            <Lock size={17} strokeWidth={1.5} style={{ color: 'var(--color-ink-700)' }} />
          </div>
          <p style={{ fontWeight: 600, fontSize: 14.5, color: 'var(--color-ink-900)', margin: '0 0 6px' }}>
            Details are locked
          </p>
          <p style={{ fontSize: 12.5, color: 'var(--color-ink-500)', lineHeight: 1.5, margin: '0 0 14px' }}>
            This scored lead is past your monthly reveal allowance. Your allowance
            resets at the start of next month.
          </p>
          <Link
            href="/settings"
            style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              height: 34, padding: '0 16px',
              background: 'var(--color-accent)', color: 'var(--text-on-accent)',
              borderRadius: 'var(--radius-pill)',
              fontSize: 13, fontWeight: 600, textDecoration: 'none',
            }}
          >
            Upgrade for unlimited
          </Link>
        </div>
      </div>
    </div>
  )
}
