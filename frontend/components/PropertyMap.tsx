'use client'
/**
 * Interactive service-area map.
 *
 * Two zoom-driven layers over a free basemap:
 *   • zoomed out  → a geohash-6 choropleth (cell rectangles decoded client-side
 *                   from the cell string) shaded by how prospective the block is.
 *   • zoomed in   → individual property pins (clustered), fetched per-viewport.
 *
 * A toggle switches the color basis between recent intent signals (default) and
 * lead-score grade. Both metrics ride along in every payload, so toggling just
 * recolors the existing GeoJSON — no refetch. Colors come from the app's
 * design-system CSS variables so the map matches the rest of the UI.
 *
 * MapLibre is imported lazily inside an effect (never at module scope) so it
 * never touches `window` during SSR.
 */
import { useEffect, useRef, useState, useCallback, useSyncExternalStore, type CSSProperties, type ReactNode } from 'react'
import Link from 'next/link'
import { ArrowLeft, Home, RefreshCw, Signal, Award, Grid3x3, Sparkles, Zap, X, SlidersHorizontal, ChevronDown, ChevronUp, MapPin } from 'lucide-react'
import ngeohash from 'ngeohash'
import { gradeVarName, GRADE_TOKENS, GRADE_ACTION, type Grade } from '@/lib/gradeColors'
import { resolveBasemap, registerPmtilesProtocol, needsPmtiles, OSM_RASTER } from '@/lib/mapStyle'
import { registerPinSprites, spriteId, type PinPalette } from '@/lib/mapPins'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { Map as MLMap, GeoJSONSource, MapMouseEvent } from 'maplibre-gl'
import { getMapCells, getMapProperties, getMapZips, getLead, getGeoHeatmap, getGeoClusters, prospectArea, getGeoEvents } from '@/lib/api'
import { serviceAreaBounds, serviceAreaLabel, clampToServiceArea, clampBoundsToServiceArea } from '@/lib/serviceArea'
import { AuthGuard } from '@/components/AuthGuard'
import { ContactDrawer } from '@/components/ContactDrawer'
import { ToastStack, useToast } from '@/components/Toast'
import type { MapCell, MapPoint, MapZip, Lead, LeadStatus, HeatmapCell, HeatmapMetric } from '@/lib/types'

type ColorMode = 'signals' | 'score'

// Below this zoom we show the choropleth; at/above it we swap to property pins.
const PIN_ZOOM = 13
// Houston — the app's primary service area (matches the seed/HCAD data).
const HOME: [number, number] = [-95.3698, 29.7604]

const STATUSES: LeadStatus[] = [
  'new', 'contacted', 'qualified', 'quote_sent', 'won', 'lost', 'not_interested', 'converted',
]

// Resolve design-system CSS variables to concrete hex (WebGL can't read vars).
//
// Grade colors are looked up through lib/gradeColors so the map cannot drift
// from ScoreBadge again — it previously painted grade B in `--color-accent`,
// the app's interactive turquoise, which made B pins read as selected controls.
//
// Fallbacks are the dark-system token values rather than the old Tailwind-ish
// hexes that used to sit here: if getComputedStyle ever returns empty (SSR-ish
// edge, very early paint) the map should degrade to Axon's palette, not to a
// light-theme one that no longer exists anywhere in the app.
function readPalette() {
  const cs = getComputedStyle(document.documentElement)
  const v = (name: string, fallback: string) => cs.getPropertyValue(name).trim() || fallback
  const grade = (g: Grade, fallback: string) => v(gradeVarName(g) as string, fallback)
  return {
    none:   v('--color-ink-200', '#404854'),
    cool:   v('--color-ocean',   '#3fa6da'),
    line:   v('--color-ink-300', '#5f6b7c'),
    accent: v('--color-accent',  '#00a396'),   // UI affordance only — never a data category
    // Grade ramp, keyed to the shared source of truth.
    gradeA: grade('A', '#32a467'),
    gradeB: grade('B', '#3fa6da'),
    gradeC: grade('C', '#f0b726'),
    gradeD: grade('D', '#e76a6e'),
    // Overlay semantics, deliberately named for what they *mean* rather than
    // for their hue, so an overlay can be recolored without anyone wondering
    // whether it also moves a lead grade. They currently share hues with the
    // grade ramp; that is a coincidence of the palette, not a coupling.
    heatLow:  v('--color-ocean',   '#3fa6da'),  // heatmap: coolest
    heatMid:  v('--color-gold',    '#f0b726'),
    heatHigh: v('--color-rose',    '#f5498b'),  // heatmap: hottest
    customer: v('--color-moss',    '#32a467'),  // customer-cluster hulls
    alert:    v('--color-danger',  '#e76a6e'),  // active event polygons
    // Pin artwork: slate body, light letter, muted border for "no grade".
    body:     v('--color-surface',  '#2f343c'),
    ink:      v('--color-ink-900',  '#f6f7f9'),
    neutral:  v('--color-ink-300',  '#5f6b7c'),
  }
}

/** The subset of the palette the pin sprites need, in their own shape. */
function pinPalette(p: Palette): PinPalette {
  return {
    gradeA: p.gradeA, gradeB: p.gradeB, gradeC: p.gradeC, gradeD: p.gradeD,
    body: p.body, ink: p.ink, neutral: p.neutral,
    signal: p.gradeC,  // gold badge — "there's recent intent here"
  }
}
type Palette = ReturnType<typeof readPalette>

// ── color logic (shared by cells + pins) ─────────────────────────────────────────

function cellColor(c: MapCell, mode: ColorMode, p: Palette): string {
  if (mode === 'signals') {
    // Three steps, not four: the old middle branch read
    // `p.accent === p.gold ? p.danger : p.gold`, a self-comparison of two
    // distinct tokens that always took the `p.gold` arm, so bands 2 and 3 were
    // the same color.
    if (c.signal_count <= 0) return p.none
    if (c.signal_count <= 3) return p.gradeC
    return p.gradeD
  }
  // score: shade by the cell's average lead score (higher = better prospect)
  const s = c.avg_score
  if (s == null) return p.none
  if (s >= 80) return p.gradeA
  if (s >= 65) return p.gradeB
  if (s >= 50) return p.gradeC
  return p.gradeD
}

function pointColor(pt: MapPoint, mode: ColorMode, p: Palette): string {
  if (mode === 'signals') return pt.signals.length > 0 ? p.gradeD : p.cool
  switch (pt.score_grade) {
    case 'A': return p.gradeA
    case 'B': return p.gradeB
    case 'C': return p.gradeC
    case 'D': return p.gradeD
    default:  return p.none
  }
}

// ── GeoJSON builders ─────────────────────────────────────────────────────────────

function cellsToGeoJSON(cells: MapCell[], mode: ColorMode, p: Palette) {
  return {
    type: 'FeatureCollection' as const,
    features: cells.map(c => {
      const [minLat, minLng, maxLat, maxLng] = ngeohash.decode_bbox(c.cell)
      return {
        type: 'Feature' as const,
        properties: {
          cell: c.cell,
          name: c.name ?? '',
          leads: c.leads,
          signal_count: c.signal_count,
          avg_score: c.avg_score ?? 0,
          color: cellColor(c, mode, p),
        },
        geometry: {
          type: 'Polygon' as const,
          coordinates: [[
            [minLng, minLat], [maxLng, minLat], [maxLng, maxLat],
            [minLng, maxLat], [minLng, minLat],
          ]],
        },
      }
    }),
  }
}

/**
 * Property pins → GeoJSON.
 *
 * Carries the fields the pin sprite, cluster aggregation and hover card all read
 * — `grade`, `status`, `score`, `hasSignal` — rather than only a precomputed
 * `color`. The API has always sent these; the renderer used to throw them away
 * and draw an undifferentiated dot.
 *
 * `sprite` is resolved here rather than in a MapLibre expression because the
 * sprite id depends on the active color mode, which an expression over feature
 * properties can't see. `color` is kept for the cluster bubbles, which shade by
 * their dominant grade.
 */
function pointsToGeoJSON(points: MapPoint[], mode: ColorMode, p: Palette) {
  return {
    type: 'FeatureCollection' as const,
    features: points.map(pt => {
      const hasSignal = pt.signals.length > 0
      // In signals mode every pin shares one shape and splits on signal state,
      // so the grade ramp shouldn't leak into it.
      const grade = mode === 'signals' ? (hasSignal ? 'S' : 'N') : (pt.score_grade ?? 'N')
      return {
        type: 'Feature' as const,
        properties: {
          id: pt.id,
          address: pt.address ?? '',
          grade,
          status: pt.status,
          score: pt.lead_score ?? null,
          signals: pt.signals.join(', '),
          hasSignal,
          sprite: spriteId(grade, hasSignal),
          color: pointColor(pt, mode, p),
        },
        geometry: { type: 'Point' as const, coordinates: [pt.longitude, pt.latitude] },
      }
    }),
  }
}

// H3 heatmap hexes → GeoJSON, with a normalized 0–1 `intensity` for shading.
function heatToGeoJSON(cells: HeatmapCell[]) {
  const max = Math.max(1, ...cells.map(c => c.value ?? 0))
  return {
    type: 'FeatureCollection' as const,
    features: cells
      .filter(c => c.boundary && c.boundary.length >= 3)
      .map(c => ({
        type: 'Feature' as const,
        properties: {
          h3: c.h3,
          value: c.value ?? 0,
          intensity: (c.value ?? 0) / max,
          leads: c.leads,
          customers: c.customers,
        },
        geometry: {
          type: 'Polygon' as const,
          coordinates: [[...c.boundary!, c.boundary![0]]],
        },
      })),
  }
}

// Cluster hulls come back as a GeoJSON FeatureCollection; drop the null-geometry
// (too-small) clusters before handing it to MapLibre.
function clustersToGeoJSON(fc: { features: Array<{ geometry: unknown }> } | null) {
  const features = (fc?.features ?? []).filter(f => f.geometry != null)
  return { type: 'FeatureCollection' as const, features: features as GeoJSON.Feature[] }
}

// Event polygons come back as a GeoJSON FeatureCollection (properties carry an
// `active` flag used to shade them); drop any null geometry.
function eventsToGeoJSON(fc: { features: Array<{ geometry: unknown }> } | null) {
  const features = (fc?.features ?? []).filter(f => f.geometry != null)
  return { type: 'FeatureCollection' as const, features: features as GeoJSON.Feature[] }
}

// Tracks a media query on the client; `false` during SSR so the desktop layout
// is the hydration baseline.
function useMediaQuery(query: string) {
  const subscribe = useCallback((onChange: () => void) => {
    const mq = window.matchMedia(query)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [query])
  return useSyncExternalStore(subscribe, () => window.matchMedia(query).matches, () => false)
}

// ── component ─────────────────────────────────────────────────────────────────────

function PropertyMapInner() {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MLMap | null>(null)
  const paletteRef = useRef<Palette | null>(null)
  const cellsRef = useRef<MapCell[]>([])
  const pointsRef = useRef<MapPoint[]>([])
  const fittedRef = useRef(false)
  const moveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Mirrors `heatmap` state so the zoom handler (created once at init) can keep
  // the choropleth hidden while the heatmap overlay is on.
  const heatmapRef = useRef(false)
  // Fontstack the active basemap's glyph server actually serves. Set before the
  // map is constructed and read when the symbol layers are added.
  const fontRef = useRef<string>(OSM_RASTER.font)

  const [mode, setMode] = useState<ColorMode>('signals')
  const [vertical, setVertical] = useState('')
  const [status, setStatus] = useState('')
  const [signalDays, setSignalDays] = useState(90)
  const [loading, setLoading] = useState(false)
  const [zoomedIn, setZoomedIn] = useState(false)
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null)
  // Geo overlays (Phase 3): H3 heatmap + customer-cluster hulls with a
  // "prospect this area" action.
  const [heatmap, setHeatmap] = useState(false)
  const [heatMetric, setHeatMetric] = useState<HeatmapMetric>('density')
  const [showClusters, setShowClusters] = useState(false)
  const [selectedCluster, setSelectedCluster] = useState<{ label: number; count: number } | null>(null)
  const [prospecting, setProspecting] = useState(false)
  const [showEvents, setShowEvents] = useState(false)
  // ZIP jump control: the account's own ZIPs, loaded lazily the first time the
  // picker is opened (most sessions never touch it).
  const [zips, setZips] = useState<MapZip[]>([])
  const [zipOpen, setZipOpen] = useState(false)
  const [zipQuery, setZipQuery] = useState('')
  const [zipsLoading, setZipsLoading] = useState(false)
  const [activeZip, setActiveZip] = useState<string | null>(null)
  const { toasts, show: showToast, dismiss: dismissToast } = useToast()
  // Mobile layout: controls collapse behind a Filters button, legend collapses.
  const isMobile = useMediaQuery('(max-width: 767px)')
  const [showControls, setShowControls] = useState(false)
  // MapLibre v6 dropped the WebGL1 fallback path, so on a device without WebGL2
  // (iOS 14, older Androids — roughly 4% of traffic) the Map constructor throws.
  // Track it so the surface explains itself instead of showing a blank rectangle.
  const [glUnsupported, setGlUnsupported] = useState(false)
  // Id of the pin under the cursor / currently open in the drawer. Drives the
  // `pin-highlight` layer's filter.
  const [activePin, setActivePin] = useState<number | null>(null)

  const filters = { vertical: vertical || undefined, status: status || undefined, signal_days: signalDays }

  // Recolor existing GeoJSON in place — used by the toggle (no refetch).
  const recolor = useCallback((m: ColorMode) => {
    const map = mapRef.current, pal = paletteRef.current
    if (!map || !pal) return
    ;(map.getSource('cells') as GeoJSONSource | undefined)
      ?.setData(cellsToGeoJSON(cellsRef.current, m, pal))
    ;(map.getSource('points') as GeoJSONSource | undefined)
      ?.setData(pointsToGeoJSON(pointsRef.current, m, pal))
  }, [])

  const loadCells = useCallback(async () => {
    const map = mapRef.current, pal = paletteRef.current
    if (!map || !pal) return
    setLoading(true)
    try {
      const cells = await getMapCells(filters)
      cellsRef.current = cells
      ;(map.getSource('cells') as GeoJSONSource | undefined)?.setData(cellsToGeoJSON(cells, mode, pal))
      // Fit to the data once on first load so users land on their territory.
      // Clamped to the service area: a handful of mis-geocoded rows (a lat/lng
      // in another state) would otherwise drag the opening view out to a
      // continental zoom. Falls back to the whole service area if nothing is
      // inside it.
      if (!fittedRef.current && cells.length) {
        const located = cells.filter(c => c.lat != null && c.lng != null)
        const dataBounds = clampToServiceArea(
          located.map(c => c.lng as number),
          located.map(c => c.lat as number),
        )
        map.fitBounds(dataBounds ?? serviceAreaBounds(), {
          padding: 60, maxZoom: 12, duration: 0,
        })
        fittedRef.current = true
      }
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Failed to load map regions', 'error')
    } finally {
      setLoading(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vertical, status, signalDays, mode, showToast])

  const loadPoints = useCallback(async () => {
    const map = mapRef.current, pal = paletteRef.current
    if (!map || !pal || map.getZoom() < PIN_ZOOM) return
    const b = map.getBounds()
    setLoading(true)
    try {
      const points = await getMapProperties(
        { min_lat: b.getSouth(), min_lng: b.getWest(), max_lat: b.getNorth(), max_lng: b.getEast() },
        filters,
      )
      pointsRef.current = points
      ;(map.getSource('points') as GeoJSONSource | undefined)?.setData(pointsToGeoJSON(points, mode, pal))
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Failed to load properties', 'error')
    } finally {
      setLoading(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vertical, status, signalDays, mode, showToast])

  // The 'moveend' handler is registered once, inside the init effect, so it would
  // otherwise capture the FIRST render's loadPoints and keep refetching with the
  // filters/mode that were active at mount — silently undoing a filter as soon as
  // the user pans, or jumps to a ZIP. Mirror the live callback in a ref (the same
  // trick heatmapRef uses above) so the handler always calls the current one.
  const loadPointsRef = useRef(loadPoints)
  useEffect(() => { loadPointsRef.current = loadPoints }, [loadPoints])

  const loadZips = useCallback(async () => {
    setZipsLoading(true)
    try {
      setZips(await getMapZips({ vertical: vertical || undefined, status: status || undefined }))
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Failed to load ZIP codes', 'error')
    } finally {
      setZipsLoading(false)
    }
  }, [vertical, status, showToast])

  const toggleZipPicker = useCallback(() => {
    const opening = !zipOpen
    setZipOpen(opening)
    if (opening) {
      setZipQuery('')
      loadZips()
    }
  }, [zipOpen, loadZips])

  // Fit to the ZIP's actual extent rather than flying to a centroid at a guessed
  // zoom, so the whole ZIP frames correctly whatever its shape. The resulting
  // moveend drives the normal pin fetch.
  const jumpToZip = useCallback((z: MapZip) => {
    const map = mapRef.current
    if (!map) return
    setActiveZip(z.zip)
    setZipOpen(false)
    map.fitBounds(
      clampBoundsToServiceArea([[z.min_lng, z.min_lat], [z.max_lng, z.max_lat]]),
      { padding: 48, maxZoom: 15, duration: 600 },
    )
  }, [])

  const openLead = useCallback(async (id: number) => {
    try {
      // Keep the pin lit while its drawer is open, so it's obvious which house
      // the panel is describing.
      setActivePin(id)
      setSelectedLead(await getLead(id))
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Failed to open lead', 'error')
    }
  }, [showToast])

  const loadHeatmap = useCallback(async () => {
    const map = mapRef.current
    if (!map) return
    setLoading(true)
    try {
      const res = await getGeoHeatmap(heatMetric)
      if (!res.available) {
        showToast('Heatmap needs the H3 index — run cluster recompute or install h3.', 'error')
      }
      ;(map.getSource('heat') as GeoJSONSource | undefined)?.setData(heatToGeoJSON(res.cells))
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Failed to load heatmap', 'error')
    } finally {
      setLoading(false)
    }
  }, [heatMetric, showToast])

  const loadClusters = useCallback(async () => {
    const map = mapRef.current
    if (!map) return
    try {
      const fc = await getGeoClusters()
      ;(map.getSource('clusters-hull') as GeoJSONSource | undefined)?.setData(clustersToGeoJSON(fc))
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Failed to load clusters', 'error')
    }
  }, [showToast])

  const loadEvents = useCallback(async () => {
    const map = mapRef.current
    if (!map) return
    try {
      const fc = await getGeoEvents()
      ;(map.getSource('events') as GeoJSONSource | undefined)?.setData(eventsToGeoJSON(fc))
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Failed to load events', 'error')
    }
  }, [showToast])

  const handleProspect = useCallback(async (clusterLabel: number) => {
    setProspecting(true)
    try {
      const r = await prospectArea({ seed: { cluster_id: clusterLabel }, vertical: vertical || undefined })
      if (r.status === 'skipped_recent_cell') {
        showToast('Already prospected this area in the last 14 days.', 'success')
      } else {
        showToast(`Prospected: ${r.ingested ?? 0} new lead(s) ingested, ${r.scored ?? 0} scored.`, 'success')
      }
      setSelectedCluster(null)
      // Reflect the freshly ingested leads.
      loadCells()
      loadPoints()
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Prospecting failed', 'error')
    } finally {
      setProspecting(false)
    }
  }, [vertical, showToast, loadCells, loadPoints])

  // ── map init (once) ───────────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false
    let map: MLMap | null = null
    // One-shot latch: interaction listeners must survive a style swap without
    // being registered twice. See the note in setupLayers.
    let handlersBound = false
    let viewportHandlersBound = false
    // The basemap fallback is one-way and one-time; without this a flapping
    // provider could ping-pong the style.
    let basemapFellBack = false

    ;(async () => {
      // MapLibre v6 ships ESM with NO default export — `(await import(...)).default`
      // is `undefined` and every `maplibregl.X` below would throw. Take the module
      // namespace instead. (v4 had a default; this is the v4→v6 break.)
      const maplibregl = await import('maplibre-gl')
      if (cancelled || !containerRef.current) return

      // Point the worker at the copy in /public. Next's bundlers rewrite the
      // worker URL without emitting its `maplibre-gl-shared.mjs` sibling, so the
      // worker throws on its first import and the map mounts but never requests a
      // tile — a silent, production-only failure. scripts/copy-maplibre-worker.mjs
      // puts both files there via prebuild/predev. Idempotent: setting the same
      // URL twice is harmless, and this effect runs once.
      maplibregl.setWorkerUrl('/maplibre/maplibre-gl-worker.mjs')

      paletteRef.current = readPalette()

      // Which basemap we're on decides the glyph endpoint, and therefore which
      // fontstack the cluster-count layer may ask for. Resolve both together —
      // see lib/mapStyle for why a mismatch fails silently.
      const basemap = resolveBasemap()
      fontRef.current = basemap.font
      if (needsPmtiles(basemap.style)) await registerPmtilesProtocol(maplibregl)
      if (cancelled) return

      try {
        map = new maplibregl.Map({
          container: containerRef.current,
          style: basemap.style as string,
          center: HOME,
          zoom: 10,
          // Hard-constrain panning/zooming to the configured service area. Widening
          // coverage is a one-entry change in lib/serviceArea.ts — see SERVICE_REGIONS.
          maxBounds: serviceAreaBounds(),
        })
      } catch (err) {
        // The constructor throws synchronously when a WebGL2 context can't be
        // created. Nothing below can run, so bail to the explanatory fallback.
        console.error('[map] WebGL2 unavailable', err)
        setGlUnsupported(true)
        return
      }
      mapRef.current = map
      map.addControl(new maplibregl.NavigationControl(), 'top-right')

      // Add our data layers as soon as the *style JSON* is parsed — deliberately
      // NOT on 'load', which also waits for the basemap's first tiles. If the
      // tile provider is slow or unreachable, 'load' can never fire, which would
      // silently leave the map with no cells/pins.
      //
      // The only precondition for addSource/addLayer is Style._loaded, which
      // MapLibre sets immediately BEFORE it fires 'styledata'. Do NOT gate on
      // map.isStyleLoaded(): that is Style.loaded(), which additionally requires
      // every source's tiles and the sprite to have finished downloading, so it
      // is always false on the single 'styledata' tick the initial load emits.
      // Tile completion fires 'sourcedata', not 'styledata', so a handler that
      // bails on isStyleLoaded() is never retried and the overlay never appears.
      const setupLayers = () => {
        if (!map || map.getLayer('cell-fill')) return
        // Fire-and-forget: MapLibre draws symbols as their images arrive, so the
        // layer can be added before registration finishes. Re-run after a style
        // swap too, which drops registered images along with the layers.
        void registerPinSprites(map, pinPalette(paletteRef.current!))
        // Choropleth (cells)
        map.addSource('cells', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
        map.addLayer({
          id: 'cell-fill', type: 'fill', source: 'cells',
          paint: { 'fill-color': ['get', 'color'], 'fill-opacity': 0.45 },
        })
        map.addLayer({
          id: 'cell-line', type: 'line', source: 'cells',
          paint: { 'line-color': paletteRef.current!.line, 'line-width': 0.5 },
        })

        // Pins (clustered)
        map.addSource('points', {
          type: 'geojson', data: { type: 'FeatureCollection', features: [] },
          cluster: true, clusterRadius: 50, clusterMaxZoom: 16,
        })
        map.addLayer({
          id: 'clusters', type: 'circle', source: 'points', filter: ['has', 'point_count'],
          paint: {
            'circle-color': paletteRef.current!.cool,
            'circle-opacity': 0.85,
            'circle-radius': ['step', ['get', 'point_count'], 14, 25, 20, 100, 28],
          },
        })
        // `text-font` is pinned rather than left to the style-spec default of
        // ['Open Sans Regular', 'Arial Unicode MS Regular'] — MapLibre requests
        // every entry in the stack, so a default that names a font the glyph
        // server lacks breaks the layer. See the note at the property below.
        map.addLayer({
          id: 'cluster-count', type: 'symbol', source: 'points', filter: ['has', 'point_count'],
          layout: {
            'text-field': ['get', 'point_count_abbreviated'],
            'text-size': 12,
            // Not hardcoded: each basemap serves its own fontstack names and
            // MapLibre requests exactly what it's given. OpenFreeMap has
            // 'Noto Sans Regular' and 404s on 'Open Sans Regular';
            // fonts.openmaptiles.org is the reverse and answers unknown stacks
            // with an HTML error page under HTTP 200, which the pbf decoder
            // throws on as "Unimplemented type: 4". lib/mapStyle keeps the
            // style and its font together so they can't drift apart.
            'text-font': [fontRef.current],
          },
          paint: { 'text-color': '#ffffff' },
        })
        // Hover/selected highlight, drawn UNDER the pins.
        //
        // A separate layer rather than extra sprites: two more states across six
        // grades would have doubled the sprite set for what is really one glow.
        // It filters on the id in React state rather than using `feature-state`,
        // because feature-state needs a stable feature id via `promoteId`, and
        // this source also sets `cluster: true` — the two don't compose
        // reliably. A filter costs nothing here and has no such dependency.
        map.addLayer({
          id: 'pin-highlight', type: 'circle', source: 'points',
          filter: ['==', ['get', 'id'], -1],
          paint: {
            'circle-color': paletteRef.current!.accent,
            'circle-opacity': 0.28,
            'circle-radius': 20,
            'circle-stroke-width': 2,
            'circle-stroke-color': paletteRef.current!.accent,
          },
        })

        // Branded pins. Bigger on touch so they're tappable with a thumb.
        const coarsePointer = window.matchMedia('(pointer: coarse)').matches
        map.addLayer({
          id: 'pin', type: 'symbol', source: 'points', filter: ['!', ['has', 'point_count']],
          layout: {
            'icon-image': ['get', 'sprite'],
            'icon-size': coarsePointer ? 1 : 0.82,
            // The diamond's lower vertex is the anchor, so the point sits on the
            // coordinate rather than the shape's centre.
            'icon-anchor': 'bottom',
            // Collision detection is the single biggest symbol-layer cost, and
            // clustering already handles decluttering. Skip it.
            'icon-allow-overlap': true,
            'icon-ignore-placement': true,
            // A-grade pins win any remaining overlap.
            'symbol-sort-key': ['match', ['get', 'grade'], 'A', 1, 'B', 2, 'C', 3, 'D', 4, 5],
          },
        })

        // H3 heatmap (Phase 3) — hidden until toggled on. Shaded by normalized
        // intensity from cool → gold → hot.
        map.addSource('heat', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
        map.addLayer({
          id: 'heat-fill', type: 'fill', source: 'heat',
          layout: { visibility: 'none' },
          paint: {
            'fill-color': ['interpolate', ['linear'], ['get', 'intensity'],
              0, paletteRef.current!.heatLow, 0.5, paletteRef.current!.heatMid, 1, paletteRef.current!.heatHigh],
            'fill-opacity': 0.55,
          },
        })

        // Customer-cluster hulls (Phase 3) — hidden until toggled; click to prospect.
        map.addSource('clusters-hull', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
        map.addLayer({
          id: 'cluster-hull-fill', type: 'fill', source: 'clusters-hull',
          layout: { visibility: 'none' },
          paint: { 'fill-color': paletteRef.current!.customer, 'fill-opacity': 0.12 },
        })
        map.addLayer({
          id: 'cluster-hull-line', type: 'line', source: 'clusters-hull',
          layout: { visibility: 'none' },
          paint: { 'line-color': paletteRef.current!.customer, 'line-width': 2, 'line-dasharray': [2, 1] },
        })

        // Event polygons (Phase 4) — hidden until toggled. Active events shade
        // hot; expired ones fade to the neutral line color.
        map.addSource('events', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
        map.addLayer({
          id: 'event-fill', type: 'fill', source: 'events',
          layout: { visibility: 'none' },
          paint: {
            'fill-color': ['case', ['get', 'active'], paletteRef.current!.alert, paletteRef.current!.line],
            'fill-opacity': 0.18,
          },
        })
        map.addLayer({
          id: 'event-line', type: 'line', source: 'events',
          layout: { visibility: 'none' },
          paint: {
            'line-color': ['case', ['get', 'active'], paletteRef.current!.alert, paletteRef.current!.line],
            'line-width': 2,
          },
        })

        // Interactions.
        //
        // Layers are recreated whenever the style is replaced (see the basemap
        // fallback below), and `map.on(...)` accumulates rather than replaces,
        // so these must bind exactly once for the lifetime of the map. The
        // `getLayer('cell-fill')` guard at the top of setupLayers doesn't cover
        // this: after setStyle the layers are genuinely gone, so setupLayers is
        // supposed to run again — it's only the listeners that must not.
        if (!handlersBound) {
          handlersBound = true
          map.on('click', 'pin', (e: MapMouseEvent & { features?: GeoJSON.Feature[] }) => {
            const id = e.features?.[0]?.properties?.id
            if (id != null) openLead(Number(id))
          })
          map.on('click', 'cell-fill', (e: MapMouseEvent) => {
            map!.easeTo({ center: e.lngLat, zoom: Math.max(map!.getZoom() + 2, PIN_ZOOM) })
          })
          map.on('click', 'clusters', async (e: MapMouseEvent & { features?: GeoJSON.Feature[] }) => {
            const f = e.features?.[0]
            const cid = f?.properties?.cluster_id
            if (cid == null) return
            const src = map!.getSource('points') as GeoJSONSource
            const zoom = await src.getClusterExpansionZoom(cid as number)
            map!.easeTo({ center: (f!.geometry as GeoJSON.Point).coordinates as [number, number], zoom })
          })
          // Clicking a customer-cluster hull opens the "prospect this area" panel.
          map.on('click', 'cluster-hull-fill', (e: MapMouseEvent & { features?: GeoJSON.Feature[] }) => {
            const props = e.features?.[0]?.properties
            if (!props) return
            setSelectedCluster({ label: Number(props.cluster_label), count: Number(props.customer_count) })
          })
          for (const layer of ['pin', 'cell-fill', 'clusters', 'cluster-hull-fill']) {
            map.on('mouseenter', layer, () => { map!.getCanvas().style.cursor = 'pointer' })
            map.on('mouseleave', layer, () => { map!.getCanvas().style.cursor = '' })
          }
          // Highlight the pin under the cursor. `mousemove` rather than
          // `mouseenter`: with pins this dense, sliding from one to its
          // neighbour doesn't re-fire enter, so the highlight would stick on
          // the wrong lead.
          map.on('mousemove', 'pin', (e) => {
            const id = e.features?.[0]?.properties?.id
            if (id != null) setActivePin(Number(id))
          })
          map.on('mouseleave', 'pin', () => setActivePin(null))
        }

        // Visibility + the first data load must run on EVERY setup, including a
        // re-setup after a style swap — only the listeners above are one-shot.
        const applyZoom = () => {
          if (!map) return
          const inPins = map.getZoom() >= PIN_ZOOM
          setZoomedIn(inPins)
          // The heatmap overlay replaces the choropleth, so keep cells hidden
          // while it's on regardless of zoom.
          const cellVis = (inPins || heatmapRef.current) ? 'none' : 'visible'
          const pinVis = inPins ? 'visible' : 'none'
          for (const l of ['cell-fill', 'cell-line']) map.setLayoutProperty(l, 'visibility', cellVis)
          for (const l of ['clusters', 'cluster-count', 'pin']) map.setLayoutProperty(l, 'visibility', pinVis)
        }
        if (!viewportHandlersBound) {
          viewportHandlersBound = true
          map.on('zoomend', applyZoom)
          map.on('moveend', () => {
            if (moveTimer.current) clearTimeout(moveTimer.current)
            moveTimer.current = setTimeout(() => {
              if (map && map.getZoom() >= PIN_ZOOM) loadPointsRef.current()
            }, 350)
          })
        }

        // Both run on every setup: after a style swap the layers are new, so
        // their visibility has to be reapplied and their data refetched.
        applyZoom()
        loadCells()
      }

      // Registered synchronously after construction, so the 'styledata' emitted
      // from Style._load() can never be missed. setupLayers is idempotent
      // (guards on cell-fill), so later style events — sprite loads, style
      // swaps — are harmless no-ops. The direct call covers the edge case of a
      // style that was somehow already fully loaded by this point.
      // Basemap fallback.
      //
      // The default basemap is a remote vector style, so it can be unreachable:
      // a provider outage, a corporate network that blocks it, an operator
      // typo in NEXT_PUBLIC_MAP_STYLE. Without this the map degrades to a blank
      // canvas — the data layers still draw (that's the 'styledata'-not-'load'
      // contract above), but with no streets under them they're unreadable.
      //
      // So: on a style-load failure, fall back once to the bundled raster style,
      // which needs no key and no configuration. One-way and one-time, so a
      // flapping provider can't ping-pong the basemap. Swapping the style drops
      // every layer, which is why setupLayers is re-entrant and why the listener
      // latches above exist.
      // v6 fully types map events, so let the listener signature be inferred
      // rather than hand-rolling one.
      map.on('error', (e) => {
        const failedToLoadStyle = !basemapFellBack && !map!.isStyleLoaded()
        if (!failedToLoadStyle) return
        basemapFellBack = true
        console.warn(
          `[map] basemap "${basemap.label}" failed to load; falling back to ${OSM_RASTER.label}.`,
          e.error,
        )
        fontRef.current = OSM_RASTER.font
        map!.setStyle(OSM_RASTER.style as unknown as string)
      })

      map.on('styledata', setupLayers)
      if (map.isStyleLoaded()) setupLayers()
    })()

    return () => {
      cancelled = true
      if (moveTimer.current) clearTimeout(moveTimer.current)
      map?.remove()
      mapRef.current = null
    }
  // Init once; data refresh is handled by the filter effect below.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Refetch when filters change (both layers stay consistent).
  useEffect(() => {
    if (!mapRef.current) return
    loadCells()
    if (zoomedIn) loadPoints()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vertical, status, signalDays])

  // Push the hovered/selected pin into the highlight layer's filter. Cheap:
  // one filter update, no source data churn.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !map.getLayer('pin-highlight')) return
    map.setFilter('pin-highlight', ['==', ['get', 'id'], activePin ?? -1])
  }, [activePin])

  // Toggle recolors in place — instant, no refetch.
  useEffect(() => { recolor(mode) }, [mode, recolor])

  // Heatmap overlay: show/hide the hex layer, keep the choropleth suppressed
  // while it's on, and (re)load when turned on or the metric changes.
  useEffect(() => {
    const map = mapRef.current
    heatmapRef.current = heatmap
    if (!map || !map.getLayer('heat-fill')) return
    map.setLayoutProperty('heat-fill', 'visibility', heatmap ? 'visible' : 'none')
    const inPins = map.getZoom() >= PIN_ZOOM
    const cellVis = (inPins || heatmap) ? 'none' : 'visible'
    for (const l of ['cell-fill', 'cell-line']) map.setLayoutProperty(l, 'visibility', cellVis)
    if (heatmap) loadHeatmap()
  }, [heatmap, heatMetric, loadHeatmap])

  // Cluster-hull overlay: show/hide and load on demand.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !map.getLayer('cluster-hull-fill')) return
    const vis = showClusters ? 'visible' : 'none'
    for (const l of ['cluster-hull-fill', 'cluster-hull-line']) map.setLayoutProperty(l, 'visibility', vis)
    if (showClusters) loadClusters()
  }, [showClusters, loadClusters])

  // Event-polygon overlay: show/hide and load on demand.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !map.getLayer('event-fill')) return
    const vis = showEvents ? 'visible' : 'none'
    for (const l of ['event-fill', 'event-line']) map.setLayoutProperty(l, 'visibility', vis)
    if (showEvents) loadEvents()
  }, [showEvents, loadEvents])

  const refresh = () => {
    loadCells()
    if (zoomedIn) loadPoints()
    if (heatmap) loadHeatmap()
    if (showClusters) loadClusters()
    if (showEvents) loadEvents()
  }

  // Any overlay on shows a badge on the mobile Filters button.
  const activeOverlays = [heatmap, showClusters, showEvents].filter(Boolean).length

  // Filter + overlay controls, rendered inline in the header on desktop and in
  // a collapsible panel below it on mobile.
  const filterControls = (
    <>
      <input
        value={vertical}
        onChange={e => setVertical(e.target.value)}
        placeholder="Vertical"
        style={{ width: 120, padding: '6px 10px', fontSize: 12, borderRadius: 'var(--radius-pill)', border: '1px solid var(--color-ink-200)', background: 'var(--color-paper)' }}
      />
      <select value={status} onChange={e => setStatus(e.target.value)}
        style={{ padding: '6px 10px', fontSize: 12, borderRadius: 'var(--radius-pill)', border: '1px solid var(--color-ink-200)', background: 'var(--color-paper)' }}>
        <option value="">All statuses</option>
        {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
      </select>
      {mode === 'signals' && (
        <select value={signalDays} onChange={e => setSignalDays(Number(e.target.value))}
          style={{ padding: '6px 10px', fontSize: 12, borderRadius: 'var(--radius-pill)', border: '1px solid var(--color-ink-200)', background: 'var(--color-paper)' }}>
          <option value={30}>30 days</option>
          <option value={60}>60 days</option>
          <option value={90}>90 days</option>
          <option value={180}>180 days</option>
        </select>
      )}

      {/* Geo overlays (Phase 3) */}
      <button
        onClick={() => setHeatmap(v => !v)}
        title="Toggle the H3 heatmap overlay"
        style={overlayBtn(heatmap)}
      >
        <Grid3x3 size={13} strokeWidth={1.5} /> Heatmap
      </button>
      {heatmap && (
        <select value={heatMetric} onChange={e => setHeatMetric(e.target.value as HeatmapMetric)}
          style={{ padding: '6px 10px', fontSize: 12, borderRadius: 'var(--radius-pill)', border: '1px solid var(--color-ink-200)', background: 'var(--color-paper)' }}>
          <option value="density">Customer density</option>
          <option value="avg_score">Avg score</option>
        </select>
      )}
      <button
        onClick={() => { if (showClusters) setSelectedCluster(null); setShowClusters(v => !v) }}
        title="Toggle customer clusters"
        style={overlayBtn(showClusters)}
      >
        <Sparkles size={13} strokeWidth={1.5} /> Clusters
      </button>
      <button
        onClick={() => setShowEvents(v => !v)}
        title="Toggle event polygons (hail swaths, new construction, …)"
        style={overlayBtn(showEvents)}
      >
        <Zap size={13} strokeWidth={1.5} /> Events
      </button>
    </>
  )

  return (
    <div style={{ height: '100dvh', display: 'flex', flexDirection: 'column' }}>
      <header style={{
        minHeight: isMobile ? 52 : 64, padding: isMobile ? '8px 12px' : '0 16px',
        display: 'flex', alignItems: 'center', gap: isMobile ? 8 : 10,
        borderBottom: '1px solid var(--color-ink-200)', background: 'var(--color-paper)', flexShrink: 0,
        flexWrap: 'wrap',
      }}>
        <Link href="/dashboard" className="dash-icon-btn" style={{ textDecoration: 'none', color: 'inherit' }}>
          <ArrowLeft size={15} strokeWidth={1.5} />
        </Link>
        {!isMobile && (
          <Link href="/home" title="Home" className="dash-icon-btn" style={{ textDecoration: 'none', color: 'inherit' }}>
            <Home size={15} strokeWidth={1.5} />
          </Link>
        )}
        <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 600, color: 'var(--color-ink-900)', margin: 0 }}>
          Map
        </h1>

        {/* Color-basis toggle (icon-only on mobile to fit one row) */}
        <div style={{ display: 'flex', gap: 2, background: 'var(--color-ink-100)', borderRadius: 'var(--radius-pill)', padding: 2, marginLeft: 8 }}>
          {([['signals', Signal, 'Intent signals'], ['score', Award, 'Score grade']] as const).map(([key, Icon, label]) => (
            <button
              key={key}
              onClick={() => setMode(key)}
              title={label}
              aria-label={label}
              style={{
                display: 'flex', alignItems: 'center', gap: 5, padding: isMobile ? '7px 12px' : '5px 12px',
                fontSize: 12, fontWeight: 500, borderRadius: 'var(--radius-pill)', border: 'none', cursor: 'pointer',
                background: mode === key ? 'var(--color-paper)' : 'transparent',
                color: mode === key ? 'var(--color-ink-900)' : 'var(--color-ink-400)',
                boxShadow: mode === key ? 'var(--shadow-card)' : 'none',
              }}
            >
              <Icon size={13} strokeWidth={1.5} /> {!isMobile && label}
            </button>
          ))}
        </div>

        {/* ZIP jump — deliberately outside `filterControls` so it stays visible on
            mobile instead of collapsing behind the Filters button. Navigating to a
            ZIP is the primary way to move around the map on a phone. */}
        <button
          onClick={toggleZipPicker}
          title="Jump to a ZIP code"
          aria-label="Jump to a ZIP code"
          aria-expanded={zipOpen}
          aria-haspopup="listbox"
          style={{ ...overlayBtn(zipOpen || activeZip != null), minHeight: isMobile ? 36 : undefined }}
        >
          <MapPin size={13} strokeWidth={1.5} /> {activeZip ?? 'ZIP'}
        </button>

        {!isMobile && filterControls}

        <div style={{ flex: 1 }} />
        {!isMobile && (
          <span style={{ fontSize: 11, color: 'var(--color-ink-400)' }}>
            {zoomedIn ? 'Properties' : 'Regions'} · zoom {zoomedIn ? 'out for blocks' : 'in for pins'}
          </span>
        )}
        {isMobile && (
          <button
            onClick={() => setShowControls(v => !v)}
            title="Filters & overlays"
            aria-expanded={showControls}
            style={{ ...overlayBtn(showControls || activeOverlays > 0), position: 'relative' }}
          >
            <SlidersHorizontal size={13} strokeWidth={1.5} /> Filters
            {activeOverlays > 0 && !showControls && ` · ${activeOverlays}`}
          </button>
        )}
        <button onClick={refresh} className="dash-icon-btn" title="Refresh">
          <RefreshCw size={13} strokeWidth={1.5} className={loading ? 'animate-spin' : ''} />
        </button>
      </header>

      {/* Mobile: collapsible filter panel below the header */}
      {isMobile && showControls && (
        <div style={{
          padding: '10px 12px', display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8,
          borderBottom: '1px solid var(--color-ink-200)', background: 'var(--color-paper)', flexShrink: 0,
        }}>
          {filterControls}
        </div>
      )}

      <div style={{ flex: 1, position: 'relative', minHeight: 0 }}>
        <div ref={containerRef} style={{ position: 'absolute', inset: 0 }} />
        {glUnsupported && <UnsupportedDevice />}
        {!glUnsupported && <Legend key={isMobile ? 'mobile' : 'desktop'} mode={mode} collapsible={isMobile} />}
        {isMobile && !glUnsupported && (
          <span style={{
            position: 'absolute', top: 10, left: '50%', transform: 'translateX(-50%)',
            fontSize: 11, color: 'var(--color-ink-700)', background: 'var(--color-paper)',
            border: '1px solid var(--color-ink-200)', borderRadius: 'var(--radius-pill)',
            padding: '3px 10px', boxShadow: 'var(--shadow-card)', pointerEvents: 'none', whiteSpace: 'nowrap',
          }}>
            {zoomedIn ? 'Properties · zoom out for blocks' : 'Regions · zoom in for pins'}
          </span>
        )}
        {zipOpen && (
          <ZipPicker
            zips={zips}
            loading={zipsLoading}
            query={zipQuery}
            onQuery={setZipQuery}
            onPick={jumpToZip}
            onClose={() => setZipOpen(false)}
            isMobile={isMobile}
            areaLabel={serviceAreaLabel()}
          />
        )}
        {showClusters && selectedCluster && (
          <ClusterActionPanel
            cluster={selectedCluster}
            busy={prospecting}
            onProspect={() => handleProspect(selectedCluster.label)}
            onClose={() => setSelectedCluster(null)}
          />
        )}
      </div>

      <ContactDrawer
        lead={selectedLead}
        onClose={() => { setSelectedLead(null); setActivePin(null) }}
        onStatusChange={() => refresh()}
        onLeadChange={updated => { setSelectedLead(updated); refresh() }}
        onToast={showToast}
      />
      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </div>
  )
}

// Pill style for the geo-overlay toggles, active state matching the mode toggle.
function overlayBtn(active: boolean): CSSProperties {
  return {
    display: 'flex', alignItems: 'center', gap: 5, padding: '6px 12px',
    fontSize: 12, fontWeight: 500, borderRadius: 'var(--radius-pill)', cursor: 'pointer',
    border: '1px solid var(--color-ink-200)',
    background: active ? 'var(--color-ink-900)' : 'var(--color-paper)',
    color: active ? 'var(--color-paper)' : 'var(--color-ink-700)',
  }
}

// Floating panel shown when a customer cluster is clicked — fires the Section 5
// "prospect this area" flow with the map's current vertical filter.
function ClusterActionPanel({
  cluster, busy, onProspect, onClose,
}: {
  cluster: { label: number; count: number }
  busy: boolean
  onProspect: () => void
  onClose: () => void
}) {
  return (
    <div style={{
      position: 'absolute', bottom: 16, left: '50%', transform: 'translateX(-50%)',
      background: 'var(--color-paper)', border: '1px solid var(--color-ink-200)',
      borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)',
      padding: '12px 14px', display: 'flex', alignItems: 'center', gap: 12, maxWidth: '92%',
      flexWrap: 'wrap', justifyContent: 'center',
    }}>
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-ink-900)' }}>
          Cluster #{cluster.label}
        </div>
        <div style={{ fontSize: 11, color: 'var(--color-ink-500)' }}>
          {cluster.count} active customer{cluster.count === 1 ? '' : 's'} here
        </div>
      </div>
      <button
        onClick={onProspect}
        disabled={busy}
        style={{
          display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px',
          fontSize: 12, fontWeight: 600, borderRadius: 'var(--radius-pill)', border: 'none',
          cursor: busy ? 'default' : 'pointer', opacity: busy ? 0.6 : 1,
          background: 'var(--color-accent)', color: '#ffffff',
        }}
      >
        <Sparkles size={13} strokeWidth={1.5} /> {busy ? 'Prospecting…' : 'Prospect this area'}
      </button>
      <button onClick={onClose} className="dash-icon-btn borderless" title="Close">
        <X size={15} strokeWidth={1.5} />
      </button>
    </div>
  )
}

/**
 * ZIP jump control — a bottom sheet on mobile, a dropdown on desktop.
 *
 * The list is the account's *own* ZIPs (GET /api/map/zips), so every entry is
 * guaranteed to contain leads and picking one fits the map to that ZIP's real
 * extent. Mobile affordances: full-width sheet with 44px rows, a numeric keypad
 * via inputMode, a 16px font so iOS Safari doesn't auto-zoom the page on focus,
 * and a tap-anywhere backdrop to dismiss.
 */
function ZipPicker({
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

/**
 * Shown when the browser can't give MapLibre a WebGL2 context.
 *
 * MapLibre v6 removed the WebGL1 fallback path, so this is a real outcome on
 * iOS 14 and older Androids rather than a theoretical one. The rest of the CRM
 * works fine on those devices — only the map doesn't — so this says exactly that
 * and points at the surfaces that still do the job, instead of leaving a blank
 * rectangle that reads as a broken page.
 */
function UnsupportedDevice() {
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

function ZipHint({ children }: { children: ReactNode }) {
  return <div style={{ padding: '10px 4px', fontSize: 12, color: 'var(--color-ink-500)' }}>{children}</div>
}

function Legend({ mode, collapsible }: { mode: ColorMode; collapsible?: boolean }) {
  // Collapsed by default on mobile so it doesn't cover the map (the parent
  // remounts this via `key` when crossing the breakpoint).
  const [open, setOpen] = useState(!collapsible)
  // Swatches read from the same shared source the layers paint from, so the
  // legend cannot describe a color the map isn't drawing. (It previously
  // claimed grade B was `--color-accent`; both were wrong together, which is
  // exactly why the drift went unnoticed.)
  const items = mode === 'signals'
    ? [
        { c: GRADE_TOKENS.D.fg,      t: 'Hot — recent signals' },
        { c: GRADE_TOKENS.C.fg,      t: 'Some signal activity' },
        { c: 'var(--color-ink-200)', t: 'No recent signals' },
      ]
    : (['A', 'B', 'C', 'D'] as const).map(g => ({
        c: GRADE_TOKENS[g].fg,
        t: GRADE_ACTION[g],
      }))
  return (
    <div style={{
      position: 'absolute', bottom: 16, left: 16, background: 'var(--color-paper)',
      border: '1px solid var(--color-ink-200)', borderRadius: 'var(--radius-card)',
      boxShadow: 'var(--shadow-card)', padding: '10px 12px', fontSize: 11, color: 'var(--color-ink-700)',
    }}>
      {collapsible ? (
        <button
          onClick={() => setOpen(v => !v)}
          aria-expanded={open}
          style={{
            display: 'flex', alignItems: 'center', gap: 6, padding: 0, margin: open ? '0 0 6px' : 0,
            border: 'none', background: 'transparent', cursor: 'pointer',
            fontSize: 11, fontWeight: 600, color: 'var(--color-ink-900)',
          }}
        >
          {mode === 'signals' ? 'Intent signals' : 'Lead score'}
          {open ? <ChevronDown size={12} strokeWidth={1.5} /> : <ChevronUp size={12} strokeWidth={1.5} />}
        </button>
      ) : (
        <div style={{ fontWeight: 600, marginBottom: 6, color: 'var(--color-ink-900)' }}>
          {mode === 'signals' ? 'Intent signals' : 'Lead score'}
        </div>
      )}
      {open && items.map(i => (
        <div key={i.t} style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 3 }}>
          <span style={{ width: 12, height: 12, borderRadius: 3, background: i.c, flexShrink: 0 }} />
          {i.t}
        </div>
      ))}
    </div>
  )
}

export function PropertyMap() {
  return <AuthGuard><PropertyMapInner /></AuthGuard>
}
