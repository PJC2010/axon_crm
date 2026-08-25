'use client'
import { useEffect, useRef, useState } from 'react'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { Map as MLMap, Marker } from 'maplibre-gl'
import type { Lead } from '@/lib/types'
import { GRADE_TOKENS, type Grade } from '@/lib/gradeColors'
import { resolveBasemap, registerPmtilesProtocol, needsPmtiles } from '@/lib/mapStyle'

interface Props {
  leads: Lead[]
  onOpen: (id: number) => void
}

/**
 * A pocket edition of the territory map for the no-login demo: the same
 * basemap the product uses, with the demo leads as grade-colored DOM markers.
 *
 * Deliberately simpler than PropertyMap: no data layers, no clustering, no
 * draw tools — DOM markers read CSS variables natively, so none of the WebGL
 * palette plumbing (readPalette/gradeVarName) is needed, and none of the
 * 'styledata' layer-timing invariants apply. maplibre itself is dynamically
 * imported so the demo page doesn't carry it until this tab is opened.
 */
export function DemoMap({ leads, onOpen }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<MLMap | null>(null)
  const glRef = useRef<typeof import('maplibre-gl') | null>(null)
  const markersRef = useRef<Marker[]>([])
  const didFitRef = useRef(false)
  const [status, setStatus] = useState<'loading' | 'ready' | 'failed'>('loading')

  // Latest handler without re-initing the map.
  const onOpenRef = useRef(onOpen)
  useEffect(() => { onOpenRef.current = onOpen })

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        // Same import + worker recipe as PropertyMap: MapLibre v6 is ESM with
        // no default export, and its worker must be served as a static asset
        // (scripts/copy-maplibre-worker.mjs puts it in /public/maplibre).
        const maplibregl = await import('maplibre-gl')
        maplibregl.setWorkerUrl('/maplibre/maplibre-gl-worker.mjs')
        const basemap = resolveBasemap()
        if (needsPmtiles(basemap.style)) await registerPmtilesProtocol(maplibregl)
        if (cancelled || !containerRef.current) return

        const map = new maplibregl.Map({
          container: containerRef.current,
          style: basemap.style as string,
          center: [-95.43, 29.74],
          zoom: 10.5,
        })
        map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
        map.on('error', () => { /* tile hiccups are non-fatal; markers still render */ })
        glRef.current = maplibregl
        mapRef.current = map
        setStatus('ready')
      } catch {
        if (!cancelled) setStatus('failed')
      }
    })()
    return () => {
      cancelled = true
      markersRef.current.forEach(m => m.remove())
      markersRef.current = []
      mapRef.current?.remove()
      mapRef.current = null
    }
  }, [])

  // (Re)place markers whenever the demo leads change.
  useEffect(() => {
    const map = mapRef.current
    const gl = glRef.current
    if (status !== 'ready' || !map || !gl) return

    markersRef.current.forEach(m => m.remove())
    markersRef.current = []

    const bounds = new gl.LngLatBounds()
    for (const lead of leads) {
      if (lead.latitude == null || lead.longitude == null) continue
      const grade = (lead.score_grade ?? 'C') as Grade
      const tokens = GRADE_TOKENS[grade] ?? GRADE_TOKENS.C

      const el = document.createElement('button')
      el.type = 'button'
      el.title = `${lead.address ?? lead.owner_name ?? 'Lead'} — grade ${grade}`
      el.setAttribute('aria-label', el.title)
      el.textContent = grade
      const pin: Partial<CSSStyleDeclaration> = {
        width: '26px', height: '26px', borderRadius: '50%',
        background: tokens.fg, color: 'white',
        border: '2px solid var(--color-paper)',
        boxShadow: '0 1px 6px rgba(0,0,0,0.4)',
        fontSize: '12px', fontWeight: '700', lineHeight: '22px',
        textAlign: 'center', cursor: 'pointer', padding: '0',
        fontFamily: 'var(--font-sans)',
      }
      Object.assign(el.style, pin)
      const id = lead.id
      el.addEventListener('click', () => onOpenRef.current(id))

      const marker = new gl.Marker({ element: el })
        .setLngLat([lead.longitude, lead.latitude])
        .addTo(map)
      markersRef.current.push(marker)
      bounds.extend([lead.longitude, lead.latitude])
    }
    // Fit once, on first placement — later lead changes (a status move, an
    // added pin) shouldn't yank the viewport away from where the visitor is.
    if (!didFitRef.current && !bounds.isEmpty()) {
      map.fitBounds(bounds, { padding: 60, maxZoom: 12, duration: 0 })
      didFitRef.current = true
    }
  }, [leads, status])

  if (status === 'failed') {
    return (
      <div style={{
        padding: '48px 24px', textAlign: 'center', borderRadius: 'var(--radius-card)',
        background: 'var(--color-surface)', boxShadow: 'var(--shadow-card)',
      }}>
        <p style={{ margin: 0, fontSize: 14, color: 'var(--color-ink-700)' }}>
          The map couldn&apos;t load here — it works in the full app, where every scored
          property in your ZIP codes is a pin like these.
        </p>
      </div>
    )
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
        <p style={{ margin: 0, flex: '1 1 260px', fontSize: 13, color: 'var(--color-ink-500)' }}>
          Every scored property on a map of your territory — tap a pin to open the lead.
          Sample area: Houston, TX.
        </p>
        <div style={{ display: 'flex', gap: 8 }}>
          {(['A', 'B', 'C', 'D'] as Grade[]).map(g => (
            <span key={g} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--color-ink-500)' }}>
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: GRADE_TOKENS[g].fg }} />
              {g}
            </span>
          ))}
        </div>
      </div>
      <div style={{ position: 'relative', borderRadius: 'var(--radius-card)', overflow: 'hidden', boxShadow: 'var(--shadow-card)' }}>
        <div ref={containerRef} style={{ height: 'min(60vh, 520px)', minHeight: 320, background: 'var(--color-surface)' }} />
        {status === 'loading' && (
          <div style={{
            position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 13, color: 'var(--color-ink-400)', background: 'var(--color-surface)',
          }}>
            Loading map…
          </div>
        )}
      </div>
    </div>
  )
}
