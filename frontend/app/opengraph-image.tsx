import { ImageResponse } from 'next/og'

// Social share card (1200×630). Generated at request time and wired into
// <meta property="og:image"> automatically by the App Router. Uses the brand
// palette from the design system: paper canvas, ink text, deep-ocean mark.
export const alt = 'Axon — territory intelligence for Harris County service contractors'
export const size = { width: 1200, height: 630 }
export const contentType = 'image/png'

const PAPER = '#F7F4EE'
const INK = '#16181D'
const OCEAN = '#1A5A75'

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          background: PAPER,
          padding: '72px 84px',
          fontFamily: 'sans-serif',
        }}
      >
        {/* Mark + wordmark */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 28 }}>
          <svg width="88" height="88" viewBox="0 0 32 32">
            <polygon points="16,5 27,16 16,27 5,16" fill={OCEAN} />
            <rect x="2" y="14.5" width="28" height="3" rx="1.5" fill={PAPER} />
            <rect x="14.5" y="2" width="3" height="28" rx="1.5" fill={PAPER} />
            <circle cx="16" cy="16" r="1.5" fill={INK} />
          </svg>
          <div style={{ fontSize: 64, fontWeight: 700, color: INK, letterSpacing: '-1px' }}>
            Axon
          </div>
        </div>

        {/* Headline */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <div style={{ fontSize: 58, fontWeight: 700, color: INK, lineHeight: 1.15, maxWidth: 980 }}>
            Know which properties are worth calling first
          </div>
          <div style={{ fontSize: 30, color: OCEAN, fontWeight: 600 }}>
            Territory intelligence for Harris County service contractors
          </div>
        </div>

        {/* Footer strip */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 14,
            fontSize: 24,
            color: INK,
            opacity: 0.75,
          }}
        >
          <div style={{ width: 44, height: 4, background: OCEAN, borderRadius: 2 }} />
          Every score explained · No shared leads · No contracts
        </div>
      </div>
    ),
    size,
  )
}
