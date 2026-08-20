'use client'
/**
 * Terra Draw session for the map.
 *
 * Three backend flows have been fully built and completely unreachable: a
 * territory polygon (`PUT /geo/service-area`), an event polygon (hail swaths,
 * new construction — `POST /geo/events`), and a user-dropped prospecting seed
 * (`/geo/prospect` has accepted `lat`/`lng` since it was written and the UI has
 * only ever sent `cluster_id`). All three need the same thing: let the user draw
 * on the map.
 *
 * ## Why Terra Draw, headless
 *
 * MIT, zero runtime dependencies, native TypeScript. `@mapbox/mapbox-gl-draw`
 * was never a licensing blocker — it's ISC; only the `mapbox-gl` *renderer* is
 * proprietary — but its types package depends on that proprietary renderer,
 * which drags it into the tree. We take the headless library and not the
 * prebuilt `@watergis` toolbar, because every control on this map is already
 * hand-rolled with `overlayBtn()` and a third-party toolbar would need
 * restyling to match anyway.
 *
 * **Verified on MapLibre 6.4.1 before this was written.** The adapter's peer
 * range is an unbounded `>=4` that predates v6, its README still says v4/5, and
 * its CI pins 5.24.0 — so drawing, vertex drag, feature drag and a clean
 * `stop()` were smoke-tested against the exact renderer this app ships.
 *
 * ## Scope: draw-then-confirm, no select mode
 *
 * A finished shape goes to a confirm panel rather than straight to the server,
 * so `polygon` mode's own `editable` handles adjustment and select mode isn't
 * needed. That matters on a phone: Terra Draw's own docs say select, point, line
 * and polygon are the only fully touch-supported modes, and the maintainer's
 * production site disables circle, rectangle and freehand on small screens. A
 * rep drawing a territory on a phone is a primary use case here, so the flow is
 * built out of the modes that work with a thumb.
 */
import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'
import type { Map as MLMap } from 'maplibre-gl'
import type { TerraDraw } from 'terra-draw'
import type { Palette } from './mapPalette'
import { polygonFromSnapshot, polygonStyles, pointStyles, type DrawnPolygon } from './draw'

export type DrawTool = 'territory' | 'event' | 'pin'

export interface DrawPending {
  tool: DrawTool
  polygon?: DrawnPolygon
  point?: [number, number]
}

/** Label for the confirm panel and the toolbar's active state. */
export const TOOL_LABEL: Record<DrawTool, string> = {
  territory: 'Service area',
  event: 'Event area',
  pin: 'Prospect here',
}

interface Options {
  mapRef: RefObject<MLMap | null>
  paletteRef: RefObject<Palette | null>
  /** Reported to the caller so its own click handlers can stand down. */
  onActiveChange?: (active: boolean) => void
  /**
   * True when the style is in a state that accepts `addSource`.
   *
   * The caller owns this because it owns the sentinel: it knows which of its
   * own layers proves the style is ready. Do **not** substitute
   * `map.isStyleLoaded()` — that is `Style.loaded()`, which additionally waits
   * on every source's tiles and the sprite, so behind a slow tile host it stays
   * false long after `addSource` would have worked, and the draw button would
   * read as dead.
   */
  layersReady: () => boolean
  onError?: (message: string) => void
}

/**
 * Resolve once the style will accept sources, or false on timeout.
 *
 * `draw.start()` calls `addSource` immediately and MapLibre throws
 * "Style is not done loading" if it isn't. The window is real and not
 * hypothetical: the basemap fallback calls `setStyle`, which resets the style
 * and logs "Unable to perform style diff … Rebuilding the style from scratch",
 * and a click that lands in that window used to throw into the console and
 * leave the tool silently unarmed.
 */
function whenStyleAccepts(map: MLMap, ready: () => boolean, timeoutMs = 8000): Promise<boolean> {
  if (ready()) return Promise.resolve(true)
  return new Promise(resolve => {
    const finish = (ok: boolean) => {
      clearTimeout(timer)
      map.off('styledata', check)
      resolve(ok)
    }
    const check = () => { if (ready()) finish(true) }
    const timer = setTimeout(() => finish(false), timeoutMs)
    map.on('styledata', check)
  })
}

export function useDrawTools({ mapRef, paletteRef, onActiveChange, layersReady, onError }: Options) {
  const drawRef = useRef<TerraDraw | null>(null)
  const [tool, setTool] = useState<DrawTool | null>(null)
  const [pending, setPending] = useState<DrawPending | null>(null)
  const [loading, setLoading] = useState(false)

  // The `finish` listener is registered once per session and must see the tool
  // the user picked, not the one that was current when it was registered.
  const toolRef = useRef<DrawTool | null>(null)
  useEffect(() => { toolRef.current = tool }, [tool])

  // `onActiveChange` is an inline arrow at the call site, so it has a new
  // identity every parent render. Read it through a ref: `teardown` depends on
  // this, and an unstable `teardown` makes the unmount effect below re-run its
  // *cleanup* on every render — which tore the session down the instant
  // `start()` set state, so a tool could never stay armed.
  const onActiveChangeRef = useRef(onActiveChange)
  const layersReadyRef = useRef(layersReady)
  const onErrorRef = useRef(onError)
  useEffect(() => {
    onActiveChangeRef.current = onActiveChange
    layersReadyRef.current = layersReady
    onErrorRef.current = onError
  })

  const activeRef = useRef(false)
  const notifyActive = useCallback((v: boolean) => {
    if (activeRef.current === v) return
    activeRef.current = v
    onActiveChangeRef.current?.(v)
  }, [])

  /**
   * Tear the session down completely.
   *
   * Called on unmount and — critically — before the basemap fallback swaps the
   * style. `setStyle` drops every custom layer, including the adapter's five, and
   * a later `draw.stop()` then tries to remove layers that no longer exist. This
   * component already solved that shape for its donut markers; the draw session
   * gets the same treatment rather than a new mechanism.
   */
  const teardown = useCallback(() => {
    const draw = drawRef.current
    drawRef.current = null
    if (draw) {
      try { if (draw.enabled) draw.stop() } catch { /* style already gone */ }
    }
    // Reset the mirror synchronously, not via its effect: teardown is called
    // from outside React too (the basemap fallback tears the session down before
    // swapping the style), and `start` reads `toolRef` to decide whether a click
    // is "pick this tool" or "toggle it off". Leaving it stale made re-picking
    // the tool you were just using read as a toggle-off, so the map appeared to
    // ignore the button.
    toolRef.current = null
    setTool(null)
    setPending(null)
    notifyActive(false)
  }, [notifyActive])

  // Unmount only — `teardown` is stable, so this cleanup runs once.
  useEffect(() => teardown, [teardown])

  // Escape cancels, the same way it closes the bottom sheet. With the toolbar
  // button now idempotent, this and the hint panel's X are the ways out.
  useEffect(() => {
    if (!tool) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') teardown() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [tool, teardown])

  const start = useCallback(async (next: DrawTool) => {
    const map = mapRef.current
    if (!map || loading) return

    // Idempotent, deliberately: picking the armed tool again does nothing rather
    // than toggling it off.
    //
    // The toggle version looked fine and was not: this handler awaits a dynamic
    // `import()`, and React replays the discrete click across that boundary, so
    // one physical click arrives as two `onClick` calls ~350ms apart (measured —
    // a capture-phase document listener sees exactly one native click). The
    // second one toggled the tool straight back off, and the button read as
    // dead. Cancelling is the hint panel's X or Escape, which no replay can
    // trip.
    if (tool === next) return

    setLoading(true)
    try {
      let draw = drawRef.current
      if (!draw) {
        if (!await whenStyleAccepts(map, () => layersReadyRef.current())) {
          onErrorRef.current?.('The map is still loading — try again in a moment.')
          return
        }
        if (!mapRef.current) return
        // Lazy: ~44 KB that only a user who actually draws should pay for.
        const { TerraDraw, TerraDrawPolygonMode, TerraDrawPointMode, TerraDrawRenderMode } =
          await import('terra-draw')
        const { TerraDrawMapLibreGLAdapter } = await import('terra-draw-maplibre-gl-adapter')
        if (!mapRef.current) return

        const pal = paletteRef.current
        const poly = pal ? polygonStyles(pal) : {}
        const point = pal ? pointStyles(pal) : {}

        draw = new TerraDraw({
          // `prefixId` namespaces the adapter's five layer ids so they can never
          // collide with ours. No `renderBelowLayerId`: draw handles belong
          // *above* the data being drawn over, and the only thing that re-adds
          // our layers underneath them is a style swap, which tears this down
          // first.
          adapter: new TerraDrawMapLibreGLAdapter({ map, prefixId: 'axon-draw' }),
          modes: [
            new TerraDrawPolygonMode({ editable: true, showCoordinatePoints: true, styles: poly }),
            new TerraDrawPointMode({ styles: point }),
            // Where a finished shape parks: still drawn, no longer editable, so
            // a stray tap on the confirm panel can't add a vertex.
            new TerraDrawRenderMode({ modeName: 'done', styles: { ...poly, ...point } }),
          ],
        })

        draw.on('finish', (id, ctx) => {
          if (ctx.action !== 'draw') return          // not a dragged vertex or a delete
          const current = toolRef.current
          if (!current) return
          const snapshot = drawRef.current?.getSnapshot()
          if (current === 'pin') {
            const f = drawRef.current?.getSnapshotFeature(id)
            const c = f?.geometry?.type === 'Point'
              ? (f.geometry.coordinates as [number, number])
              : null
            if (c) setPending({ tool: 'pin', point: c })
          } else {
            const polygon = polygonFromSnapshot(snapshot)
            if (polygon) setPending({ tool: current, polygon })
          }
          drawRef.current?.setMode('done')
        })

        try {
          draw.start()
        } catch (err) {
          onErrorRef.current?.('Could not start drawing on this map.')
          console.warn('[map] terra-draw failed to start', err)
          return
        }
        drawRef.current = draw
      }

      draw.clear()
      setPending(null)
      setTool(next)
      toolRef.current = next
      draw.setMode(next === 'pin' ? 'point' : 'polygon')
      notifyActive(true)
    } finally {
      setLoading(false)
    }
  }, [mapRef, paletteRef, loading, tool, notifyActive])

  /** Throw away the shape and go back to drawing with the same tool. */
  const redraw = useCallback(() => {
    const draw = drawRef.current, current = toolRef.current
    if (!draw || !current) return
    draw.clear()
    setPending(null)
    draw.setMode(current === 'pin' ? 'point' : 'polygon')
  }, [])

  /** Clear the drawing but keep the session open — used after a successful save. */
  const clear = useCallback(() => {
    drawRef.current?.clear()
    setPending(null)
  }, [])

  return { tool, pending, loading, start, redraw, clear, cancel: teardown, teardown }
}
