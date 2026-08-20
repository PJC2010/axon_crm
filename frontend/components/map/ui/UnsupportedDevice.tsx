'use client'
import Link from 'next/link'
import { MapPin } from 'lucide-react'

/**
 * Shown when the browser can't give MapLibre a WebGL2 context.
 *
 * MapLibre v6 removed the WebGL1 fallback path, so this is a real outcome on
 * iOS 14 and older Androids rather than a theoretical one — roughly 4% of
 * traffic. The rest of the CRM works fine on those devices; only the map
 * doesn't. So this says exactly that and points at the surface that still does
 * the job, instead of leaving a blank rectangle that reads as a broken page.
 */
export function UnsupportedDevice() {
  return (
    <div style={{
      position: 'absolute', inset: 0, zIndex: 4, display: 'flex',
      alignItems: 'center', justifyContent: 'center', padding: 24,
      background: 'var(--color-paper)',
    }}>
      <div style={{ maxWidth: 380, textAlign: 'center' }}>
        <MapPin size={28} strokeWidth={1.5} style={{ color: 'var(--color-ink-400)' }} />
        <div style={{
          fontFamily: 'var(--font-display)', fontSize: 17, fontWeight: 600,
          color: 'var(--color-ink-900)', margin: '10px 0 6px',
        }}>
          This device can&rsquo;t display the map
        </div>
        <p style={{ fontSize: 13, lineHeight: 1.55, color: 'var(--color-ink-500)', margin: 0 }}>
          The map needs WebGL2, which this browser doesn&rsquo;t support. Updating to a
          newer browser or device will fix it. Everything else in Axon works normally —
          your leads are all on the{' '}
          <Link href="/pipeline" style={{ color: 'var(--color-accent-300)' }}>pipeline board</Link>.
        </p>
      </div>
    </div>
  )
}
