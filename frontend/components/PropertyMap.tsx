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
import { useEffect, useRef, useState, useCallback } from 'react'
import Link from 'next/link'
import { ArrowLeft, Home, RefreshCw, Signal, Award, Grid3x3, Sparkles, Zap, SlidersHorizontal, MapPin } from 'lucide-react'
import { resolveBasemap, registerPmtilesProtocol, needsPmtiles, OSM_RASTER } from '@/lib/mapStyle'
import { registerPinSprites } from '@/lib/mapPins'
import 'maplibre-gl/dist/maplibre-gl.css'
// Must follow maplibre's own stylesheet — it re-tokenises the light-theme chrome
// MapLibre ships (popup surface, tip, attribution, controls) for the dark system.
import '@/components/map/map.css'
import type { Map as MLMap, GeoJSONSource, MapMouseEvent } from 'maplibre-gl'
import { getMapCells, getMapProperties, getMapZips, getLead, getGeoHeatmap, getGeoClusters, prospectArea, getGeoEvents, putServiceArea, createGeoEvent, getBlastRadius, searchCustomers } from '@/lib/api'
import { serviceAreaBounds, serviceAreaLabel, clampToServiceArea, clampBoundsToServiceArea } from '@/lib/serviceArea'
import { AuthGuard } from '@/components/AuthGuard'
import { ContactDrawer } from '@/components/ContactDrawer'
import { ToastStack, useToast } from '@/components/Toast'
import { useMediaQuery, MOBILE_BREAKPOINT } from '@/hooks/useMediaQuery'
import { readPalette, pinPalette, type Palette } from '@/components/map/mapPalette'
import {
  cellsToGeoJSON, pointsToGeoJSON, heatToGeoJSON, clustersToGeoJSON, eventsToGeoJSON, blastToGeoJSON,
  type ColorMode,
} from '@/components/map/geojson'
import { circleRing, ringBounds } from '@/components/map/draw'
import { padBbox, contains, VIEWPORT_PAD, type Bbox } from '@/components/map/bbox'
import { rampExpression } from '@/components/map/ramp'
import { gradeClusterProperties, createDonutManager, type DonutManager } from '@/components/map/clusterDonuts'
import { buildHoverCard, hoverFieldsFrom, buildCellCard, cellFieldsFrom } from '@/components/map/hoverCard'
import { overlayBtn, fieldStyle } from '@/components/map/ui/controlStyles'
import { useDrawTools } from '@/components/map/useDrawTools'
import { DrawToolbar, DrawHint, DrawConfirm } from '@/components/map/ui/DrawTools'
import { BlastPanel, NeighborsPrompt } from '@/components/map/ui/BlastPanel'
import { Legend } from '@/components/map/ui/Legend'
import { PlacePicker } from '@/components/map/ui/PlacePicker'
import { ClusterActionPanel } from '@/components/map/ui/ClusterActionPanel'
import { UnsupportedDevice } from '@/components/map/ui/UnsupportedDevice'
import { TruncationNotice } from '@/components/map/ui/TruncationNotice'
import { Sheet } from '@/components/ds/Sheet'
import type { MapCell, MapPoint, MapZip, Lead, LeadStatus, HeatmapMetric, NeighborHit, CustomerSearchResult } from '@/lib/types'

// Below this zoom we show the choropleth; at/above it we swap to property pins.
const PIN_ZOOM = 13
// How many pins we're willing to draw at once. Matches the server's own default
// so behaviour is unchanged; the difference is that we now *know* when we hit it
// (we request PIN_LIMIT + 1) instead of silently showing the top slice.
const PIN_LIMIT = 2000
// Blast radius for "show neighbors". Matches the server's GEO_NEIGHBOR_RADIUS_M
// default; ~150 m is the block a rep can work while the truck stays parked.
const BLAST_RADIUS_M = 150
// Houston — the app's primary service area (matches the seed/HCAD data).
const HOME: [number, number] = [-95.3698, 29.7604]

const STATUSES: LeadStatus[] = [
  'new', 'contacted', 'qualified', 'quote_sent', 'won', 'lost', 'not_interested', 'converted',
]

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
  // Mirrors `mode` for the same reason heatmapRef exists: setupLayers is built
  // once, so it would otherwise bake the basis that was active at mount and a
  // style swap would silently revert the choropleth's ramp.
  const modeRef = useRef<ColorMode>('signals')
  // Cluster donut markers. Held in a ref because the zoom/idle handlers are
  // registered once at init and would otherwise close over the first render's
  // value — the same reason loadPointsRef exists.
  const donutsRef = useRef<DonutManager | null>(null)
  // Control handlers are registered once inside the init effect, so they can't
  // close over `showToast` directly — same stale-closure trap as loadPointsRef.
  const showToastRef = useRef<(m: string, v?: 'success' | 'error') => void>(() => {})
  // Whether the primary input is a finger. Kept live rather than sampled once,
  // because it's the only thing sizing pins for touch.
  const coarsePointerRef = useRef(false)
  // Whether a draw tool currently owns the map surface. A ref because the
  // interaction handlers are registered once and would otherwise close over the
  // first render's value.
  const drawActiveRef = useRef(false)
  // The style-swap handler is registered once, so it reaches the draw session
  // through a ref rather than closing over the hook's current teardown.
  const drawTeardownRef = useRef<() => void>(() => {})
  // The padded box the current pins were fetched for. A pan stays cached while
  // the viewport is still inside it; null means "nothing trustworthy loaded".
  const fetchedBoxRef = useRef<Bbox | null>(null)
  // Reused hover Popup. One instance for the lifetime of the map: constructing
  // one per hover leaks DOM and makes the card flicker as you cross pins.
  const hoverRef = useRef<{ setLngLat: (c: [number, number]) => { setDOMContent: (n: Node) => { addTo: (m: MLMap) => void } }; remove: () => void } | null>(null)

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
  const [leadHits, setLeadHits] = useState<CustomerSearchResult[]>([])
  const [leadsLoading, setLeadsLoading] = useState(false)
  const [activeZip, setActiveZip] = useState<string | null>(null)
  const { toasts, show: showToast, dismiss: dismissToast } = useToast()
  // Mobile layout: controls collapse behind a Filters button, legend collapses.
  const isMobile = useMediaQuery(MOBILE_BREAKPOINT)
  const [showControls, setShowControls] = useState(false)
  // MapLibre v6 dropped the WebGL1 fallback path, so on a device without WebGL2
  // (iOS 14, older Androids — roughly 4% of traffic) the Map constructor throws.
  // Track it so the surface explains itself instead of showing a blank rectangle.
  const [glUnsupported, setGlUnsupported] = useState(false)
  // Id of the pin under the cursor / currently open in the drawer. Drives the
  // `pin-highlight` layer's filter.
  const [activePin, setActivePin] = useState<number | null>(null)
  // True when the viewport holds more leads than PIN_LIMIT, so the map is
  // showing a slice. Surfaced rather than hidden — see the note in loadPoints.
  const [truncated, setTruncated] = useState(false)

  const filters = { vertical: vertical || undefined, status: status || undefined, signal_days: signalDays }

  // Switch the color basis in place — the toggle never refetches, because both
  // metrics ride along in every payload.
  const recolor = useCallback((m: ColorMode) => {
    const map = mapRef.current, pal = paletteRef.current
    if (!map || !pal) return
    // Cells: one paint-property update. No data churn — the ramp reads
    // signal_count / avg_score straight off features that already carry both.
    if (map.getLayer('cell-fill')) {
      map.setPaintProperty('cell-fill', 'fill-color', rampExpression(m, pal) as never)
    }
    // Pins do need new data: each feature's `sprite` depends on the mode, and
    // that's resolved in JS rather than by an expression.
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
      ;(map.getSource('cells') as GeoJSONSource | undefined)?.setData(cellsToGeoJSON(cells))
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

  const loadPoints = useCallback(async (opts?: { force?: boolean }) => {
    const map = mapRef.current, pal = paletteRef.current
    if (!map || !pal || map.getZoom() < PIN_ZOOM) return

    const b = map.getBounds()
    const view: Bbox = {
      min_lat: b.getSouth(), min_lng: b.getWest(),
      max_lat: b.getNorth(), max_lng: b.getEast(),
    }

    // Skip the request when the last fetch already covers where we are.
    //
    // Every pan used to refetch up to 2,000 rows the client already held, even
    // for a nudge of a few pixels. We now fetch a padded box and only go back to
    // the server once the viewport leaves it — so small pans are instant because
    // the pins are already there. `force` is for filter changes, where the
    // cached box is still geometrically valid but semantically stale.
    if (!opts?.force && fetchedBoxRef.current && contains(fetchedBoxRef.current, view)) return

    const padded = padBbox(view, VIEWPORT_PAD)
    setLoading(true)
    try {
      // Ask for one more than we draw: if the server can fill it, there are more
      // leads here than we're showing, and the user deserves to know.
      const rows = await getMapProperties(padded, filters, PIN_LIMIT + 1)
      const truncated = rows.length > PIN_LIMIT
      const points = truncated ? rows.slice(0, PIN_LIMIT) : rows

      pointsRef.current = points
      fetchedBoxRef.current = padded
      setTruncated(truncated)
      ;(map.getSource('points') as GeoJSONSource | undefined)?.setData(pointsToGeoJSON(points, mode, pal))
    } catch (e) {
      // Drop the cached box so the next pan retries rather than trusting a
      // fetch that never landed.
      fetchedBoxRef.current = null
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
  useEffect(() => { showToastRef.current = showToast }, [showToast])

  // Keep the pointer-coarseness ref current and restyle the pins in place when
  // it flips. `icon-size` is a layout property, so this is a cheap update — no
  // re-registering sprites, no source churn.
  useEffect(() => {
    const mq = window.matchMedia('(pointer: coarse)')
    const apply = () => {
      coarsePointerRef.current = mq.matches
      const map = mapRef.current
      if (map?.getLayer('pin')) {
        map.setLayoutProperty('pin', 'icon-size', mq.matches ? 1 : 0.82)
      }
    }
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [])

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

  const togglePlacePicker = useCallback(() => {
    const opening = !zipOpen
    setZipOpen(opening)
    if (opening) {
      setZipQuery('')
      loadZips()
    }
  }, [zipOpen, loadZips])

  // Lead search, debounced.
  //
  // Reuses `GET /api/leads/search` rather than adding `/api/map/search`: it is
  // already account-scoped, already excludes archived rows, and already ranks
  // exact account-number hits first. The only thing it was missing was
  // coordinates, which is now two columns on its SELECT rather than a new
  // endpoint. One consequence taken deliberately: `/leads/*` is ungated while
  // `/map/*` sits behind require_module("map"), so map search inherits the
  // looser gate — correct, since it is the same data the lead list already
  // shows.
  // Whether the term is long enough to search is derived, not stored: clearing
  // the hits with a setState in the effect body is a cascading render, and the
  // stale-results case it was there to handle is better answered by not
  // rendering them.
  const searchTerm = zipQuery.trim()
  const leadSearchArmed = zipOpen && searchTerm.length >= 2

  useEffect(() => {
    if (!leadSearchArmed) return
    let cancelled = false
    const t = setTimeout(async () => {
      setLeadsLoading(true)
      try {
        const rows = await searchCustomers(searchTerm, 8)
        if (!cancelled) setLeadHits(rows)
      } catch {
        if (!cancelled) setLeadHits([])
      } finally {
        if (!cancelled) setLeadsLoading(false)
      }
    }, 250)
    return () => { cancelled = true; clearTimeout(t) }
  }, [searchTerm, leadSearchArmed])

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

  const jumpToLead = useCallback((l: CustomerSearchResult) => {
    const map = mapRef.current
    if (!map) return
    if (l.latitude == null || l.longitude == null) {
      // Not an error: `properties` doubles as the contact book, so an inbound
      // call or web-form lead genuinely has nowhere to fly to.
      showToast('That lead has no map location yet.', 'success')
      return
    }
    setZipOpen(false)
    map.easeTo({ center: [l.longitude, l.latitude], zoom: Math.max(map.getZoom(), PIN_ZOOM + 2), duration: 600 })
    openLead(l.id)
  }, [showToast, openLead])

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
      // Reflect the freshly ingested leads. Forced: prospecting adds rows inside
      // the box we already fetched, so the cache is geometrically valid and
      // semantically stale — exactly the case `force` exists for.
      loadCells()
      loadPoints({ force: true })
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Prospecting failed', 'error')
    } finally {
      setProspecting(false)
    }
  }, [vertical, showToast, loadCells, loadPoints])

  // ── blast radius ──────────────────────────────────────────────────────────────
  //
  // `getBlastRadius` has had an API client since the geo phase and no caller at
  // all. It ranks open leads around a completed job — the door-knock list for
  // verticals where the work is visible from the street — which is exactly the
  // question a map should be able to answer and couldn't.
  const [blast, setBlast] = useState<{ lead: Lead; hits: NeighborHit[]; radius: number } | null>(null)
  const [blastLoading, setBlastLoading] = useState(false)

  const clearBlast = useCallback(() => {
    setBlast(null)
    const src = mapRef.current?.getSource('blast') as GeoJSONSource | undefined
    src?.setData({ type: 'FeatureCollection', features: [] })
  }, [])

  const showNeighbors = useCallback(async (lead: Lead) => {
    const map = mapRef.current, pal = paletteRef.current
    if (!map || !pal || lead.latitude == null || lead.longitude == null) return
    setBlastLoading(true)
    try {
      const r = await getBlastRadius(lead.id, BLAST_RADIUS_M)
      // `POST /geo/neighbors` returns [] both for "no open leads nearby" and for
      // a job with no coordinates, so the client cannot tell them apart. Say the
      // true thing — that nothing came back — rather than inventing a cause.
      if (!r.neighbors.length) {
        showToast('No open leads within a short walk of this job.', 'success')
        return
      }
      const center: [number, number] = [lead.longitude, lead.latitude]
      setBlast({ lead, hits: r.neighbors, radius: r.radius_m })
      const src = map.getSource('blast') as GeoJSONSource | undefined
      src?.setData(blastToGeoJSON(center, r.radius_m, r.neighbors, pal))
      const b = ringBounds(circleRing(center, r.radius_m))
      if (b) map.fitBounds(b, { padding: 80, maxZoom: 17, duration: 600 })
      setSelectedLead(null)     // the drawer covers the answer it just produced
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Could not load neighbors', 'error')
    } finally {
      setBlastLoading(false)
    }
  }, [showToast])

  // ── draw tools ────────────────────────────────────────────────────────────────
  const drawTools = useDrawTools({
    mapRef, paletteRef,
    // `cell-fill` is added by setupLayers on the first 'styledata', so its
    // presence is proof the style accepts addSource — including after the
    // basemap fallback rebuilds the style from scratch.
    layersReady: () => !!mapRef.current?.getLayer('cell-fill'),
    onError: (m) => showToastRef.current(m, 'error'),
    onActiveChange: (active) => {
      drawActiveRef.current = active
      // A card left hanging while the user starts drawing points at a lead they
      // are no longer looking at.
      if (active) { hoverRef.current?.remove(); clearBlast() }
    },
  })
  const [savingDraw, setSavingDraw] = useState(false)
  useEffect(() => { drawTeardownRef.current = drawTools.teardown }, [drawTools.teardown])

  const saveDrawing = useCallback(async ({ eventType, name }: { eventType: string; name: string }) => {
    const p = drawTools.pending
    if (!p || savingDraw) return
    setSavingDraw(true)
    try {
      if (p.tool === 'territory' && p.polygon) {
        await putServiceArea(p.polygon)
        // The save rescored every lead in the account before it returned, so
        // both layers are stale by definition. Forced for the same reason
        // prospecting forces: the box is right, the contents aren't.
        showToast('Service area saved. Leads rescored.', 'success')
        loadCells()
        loadPoints({ force: true })
      } else if (p.tool === 'event' && p.polygon) {
        await createGeoEvent({ event_type: eventType, name: name || undefined, polygon: p.polygon })
        showToast('Event area saved.', 'success')
        if (showEvents) loadEvents()
        else setShowEvents(true)     // no point saving one you can't see
      } else if (p.tool === 'pin' && p.point) {
        const [lng, lat] = p.point
        const r = await prospectArea({ seed: { lat, lng }, vertical: vertical || undefined })
        if (r.status === 'skipped_recent_cell') {
          showToast('Already prospected this area in the last 14 days.', 'success')
        } else {
          showToast(`Prospected: ${r.ingested ?? 0} new lead(s) ingested, ${r.scored ?? 0} scored.`, 'success')
        }
        loadCells()
        loadPoints({ force: true })
      }
      drawTools.cancel()
    } catch (e) {
      // Deliberately keep the drawing: a failed save with the shape thrown away
      // means redrawing a territory by hand.
      showToast(e instanceof Error ? e.message : 'Could not save', 'error')
    } finally {
      setSavingDraw(false)
    }
  }, [drawTools, savingDraw, showToast, loadCells, loadPoints, loadEvents, showEvents, vertical])

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

      // No layer requests glyphs any more — the only text on the map is the
      // cluster count, and that moved into the donut markers' SVG, where it
      // renders in the app's own font instead of whatever the tile provider
      // serves. That also removes a whole class of silent failure; see the
      // fontstack note in lib/mapStyle for what it used to cost.
      const basemap = resolveBasemap()
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

      // "Where am I relative to my A-grade leads" is the single most useful
      // control for a rep standing on a street, and it's core MapLibre — no
      // dependency. map.css already re-tokenises .maplibregl-ctrl-group, so
      // these inherit the dark styling.
      const geolocate = new maplibregl.GeolocateControl({
        positionOptions: { enableHighAccuracy: true },
        trackUserLocation: true,
        showAccuracyCircle: true,
      })
      map.addControl(geolocate, 'top-right')
      // The map is hard-bounded to the service area, so a fix outside it is a
      // location we simply cannot pan to. Say so rather than leaving a button
      // that appears to do nothing.
      geolocate.on('outofmaxbounds', () => {
        showToastRef.current(
          `You're outside ${serviceAreaLabel()}, so the map can't jump to you.`,
          'error',
        )
      })
      // v6 types this event, so let the signature be inferred.
      geolocate.on('error', (e) => {
        // Code 1 is PERMISSION_DENIED — a decision, not a failure, so don't
        // shout about it.
        if (e.code === 1) return
        showToastRef.current('Could not get your location.', 'error')
      })

      // Scale bar: imperial, because this ships to US contractors.
      map.addControl(new maplibregl.ScaleControl({ maxWidth: 90, unit: 'imperial' }), 'bottom-right')

      // One Popup, reused for every hover. MapLibre owns the anchoring and the
      // edge-flipping; we only ever move it and swap its contents.
      hoverRef.current = new maplibregl.Popup({
        closeButton: false,
        closeOnClick: false,
        offset: 18,          // clears the pin, which is anchored at its lower vertex
        maxWidth: 'none',    // the card sets its own max-width
        className: 'map-hover-popup',
      })

      // Donut cluster markers. The manager owns marker lifecycle; it only needs
      // a factory so it never imports maplibre itself (keeping it a plain module).
      donutsRef.current = createDonutManager(
        map,
        (el, lngLat) => new maplibregl.Marker({ element: el }).setLngLat(lngLat).addTo(map!),
        paletteRef.current!,
      )

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
          paint: {
            // A continuous ramp evaluated by MapLibre, not a color baked per
            // feature in JS. Average score and signal count are ordered values,
            // so they get a gradient; switching basis is now a paint-property
            // update rather than rebuilding and re-uploading every polygon.
            'fill-color': rampExpression(modeRef.current, paletteRef.current!) as never,
            'fill-opacity': 0.45,
          },
        })
        map.addLayer({
          id: 'cell-line', type: 'line', source: 'cells',
          paint: { 'line-color': paletteRef.current!.line, 'line-width': 0.5 },
        })

        // Pins (clustered).
        //
        // `clusterProperties` makes Supercluster tally the grade mix while it
        // clusters, so the donut markers below get their proportions for free
        // rather than us counting members every frame.
        map.addSource('points', {
          type: 'geojson', data: { type: 'FeatureCollection', features: [] },
          cluster: true, clusterRadius: 50, clusterMaxZoom: 16,
          clusterProperties: gradeClusterProperties(),
        })
        // Clusters are drawn as HTML donut markers (see components/map/
        // clusterDonuts.ts), not as a circle+symbol layer pair. A proportional
        // multi-segment arc isn't expressible as a circle paint property, and
        // there are only ever a few dozen clusters on screen, so the DOM is
        // affordable here in a way it isn't for the 2,000 pins.
        //
        // An invisible hit layer keeps click/cursor handling on the GL side, so
        // the existing `click`/`mouseenter` wiring works unchanged and the
        // markers themselves stay non-interactive.
        map.addLayer({
          id: 'clusters', type: 'circle', source: 'points', filter: ['has', 'point_count'],
          paint: {
            'circle-color': paletteRef.current!.cool,
            'circle-opacity': 0,   // the donut marker is what you see
            'circle-radius': ['step', ['get', 'point_count'], 17, 25, 21, 100, 26],
          },
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
          // Both clauses matter. The id match is the actual selection; excluding
          // clusters guards the case where a cluster feature carries an `id` —
          // it doesn't today (clusters get `cluster_id`), but a highlight that
          // can latch onto a cluster is a bug waiting for a schema change.
          filter: ['all', ['!', ['has', 'point_count']], ['==', ['get', 'id'], -1]],
          paint: {
            'circle-color': paletteRef.current!.accent,
            'circle-opacity': 0.28,
            'circle-radius': 20,
            'circle-stroke-width': 2,
            'circle-stroke-color': paletteRef.current!.accent,
          },
        })

        // Branded pins. Bigger on touch so they're tappable with a thumb.
        //
        // Read from a ref that a listener keeps current, rather than sampled
        // once at init: this is the only thing sizing pins for touch, and a
        // device that changes input mode (or any hydration-order surprise) used
        // to be stuck with the wrong size for the whole session.
        const coarsePointer = coarsePointerRef.current
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

        // Blast radius (Phase 6): the ring around a completed job and its ranked
        // door-knock targets. Added last so it sits above the pins it annotates.
        //
        // The ring is a real polygon, not a `circle` layer: circle-radius is in
        // screen pixels, so a 150 m ring would grow and shrink against the
        // streets as you zoom — backwards for a "how far can I walk" overlay.
        map.addSource('blast', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
        map.addLayer({
          id: 'blast-fill', type: 'fill', source: 'blast',
          filter: ['==', ['get', 'kind'], 'ring'],
          paint: { 'fill-color': paletteRef.current!.accent, 'fill-opacity': 0.08 },
        })
        map.addLayer({
          id: 'blast-ring', type: 'line', source: 'blast',
          filter: ['==', ['get', 'kind'], 'ring'],
          paint: {
            'line-color': paletteRef.current!.accent, 'line-width': 2, 'line-dasharray': [3, 2],
          },
        })
        map.addLayer({
          id: 'blast-hit', type: 'circle', source: 'blast',
          filter: ['==', ['get', 'kind'], 'hit'],
          paint: {
            'circle-radius': coarsePointer ? 9 : 7,
            'circle-color': ['get', 'color'],
            'circle-stroke-color': paletteRef.current!.body,
            'circle-stroke-width': 2,
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
          // While a draw tool is armed, the map surface belongs to the gesture:
          // a tap is a vertex, not a lead. Terra Draw draws its own layers over
          // ours and doesn't stop MapLibre's feature clicks, so without this a
          // tap that places a corner also opens a contact drawer over the map
          // the user is drawing on.
          map.on('click', 'pin', (e: MapMouseEvent & { features?: GeoJSON.Feature[] }) => {
            if (drawActiveRef.current) return
            const id = e.features?.[0]?.properties?.id
            if (id != null) openLead(Number(id))
          })
          map.on('click', 'blast-hit', (e: MapMouseEvent & { features?: GeoJSON.Feature[] }) => {
            if (drawActiveRef.current) return
            const id = e.features?.[0]?.properties?.id
            if (id != null) openLead(Number(id))
          })
          map.on('click', 'cell-fill', (e: MapMouseEvent) => {
            if (drawActiveRef.current) return
            map!.easeTo({ center: e.lngLat, zoom: Math.max(map!.getZoom() + 2, PIN_ZOOM) })
          })
          map.on('click', 'clusters', async (e: MapMouseEvent & { features?: GeoJSON.Feature[] }) => {
            if (drawActiveRef.current) return
            const f = e.features?.[0]
            const cid = f?.properties?.cluster_id
            if (cid == null) return
            const src = map!.getSource('points') as GeoJSONSource
            const zoom = await src.getClusterExpansionZoom(cid as number)
            map!.easeTo({ center: (f!.geometry as GeoJSON.Point).coordinates as [number, number], zoom })
          })
          // Clicking a customer-cluster hull opens the "prospect this area" panel.
          map.on('click', 'cluster-hull-fill', (e: MapMouseEvent & { features?: GeoJSON.Feature[] }) => {
            if (drawActiveRef.current) return
            const props = e.features?.[0]?.properties
            if (!props) return
            setSelectedCluster({ label: Number(props.cluster_label), count: Number(props.customer_count) })
          })
          for (const layer of ['pin', 'cell-fill', 'clusters', 'cluster-hull-fill', 'blast-hit']) {
            map.on('mouseenter', layer, () => { map!.getCanvas().style.cursor = 'pointer' })
            map.on('mouseleave', layer, () => { map!.getCanvas().style.cursor = '' })
          }
          // Highlight + preview the pin under the cursor. `mousemove` rather
          // than `mouseenter`: with pins this dense, sliding from one to its
          // neighbour doesn't re-fire enter, so both the highlight and the card
          // would stick on the wrong lead.
          //
          // Everything the card shows already rides in the feature's properties,
          // so hovering costs no request — which is the point. Clicking still
          // fetches the full lead for the drawer.
          map.on('mousemove', 'pin', (e) => {
            if (drawActiveRef.current) return
            const f = e.features?.[0]
            const id = f?.properties?.id
            if (id == null) return
            setActivePin(Number(id))

            const fields = hoverFieldsFrom(f?.properties)
            const coords = (f?.geometry as GeoJSON.Point | undefined)?.coordinates
            if (!fields || !coords) return
            hoverRef.current
              ?.setLngLat(coords as [number, number])
              .setDOMContent(buildHoverCard(fields))
              .addTo(map!)
          })
          map.on('mouseleave', 'pin', () => {
            setActivePin(null)
            hoverRef.current?.remove()
          })
          // A hover card left hanging over a cluster reads as belonging to it.
          map.on('mouseenter', 'clusters', () => hoverRef.current?.remove())

          // Same treatment for choropleth cells, using the grade counts that
          // have been in every /api/map/cells response since it was written and
          // were never drawn. The cell's fill shows one average; the card shows
          // what that average is made of.
          map.on('mousemove', 'cell-fill', (e) => {
            if (drawActiveRef.current) return
            const f = e.features?.[0]
            const fields = cellFieldsFrom(f?.properties)
            if (!fields) return
            hoverRef.current
              ?.setLngLat([e.lngLat.lng, e.lngLat.lat])
              .setDOMContent(buildCellCard(fields))
              .addTo(map!)
          })
          map.on('mouseleave', 'cell-fill', () => hoverRef.current?.remove())
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
          for (const l of ['clusters', 'pin-highlight', 'pin']) map.setLayoutProperty(l, 'visibility', pinVis)
          // Donut markers are DOM, not layers, so `visibility` can't reach them —
          // they have to be torn down by hand when we leave pin mode, or they
          // float over the choropleth.
          if (!inPins) donutsRef.current?.clear()
          else donutsRef.current?.refresh()
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
          // Clusters are recomputed by Supercluster whenever the source data or
          // the zoom changes; `idle` is the point at which those results are
          // actually queryable, so it's the right moment to resync the markers.
          map.on('idle', () => {
            if (map && map.getZoom() >= PIN_ZOOM) donutsRef.current?.refresh()
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
        // Markers are DOM and survive setStyle, but the clusters they describe
        // don't — the source is rebuilt, so stale donuts would hang over the new
        // basemap until the next idle. Clear them and let setupLayers re-sync.
        donutsRef.current?.clear()
        // Same reason, one step further: setStyle drops the adapter's five
        // layers too, and a later draw.stop() would then try to remove layers
        // that no longer exist. Tear the session down while it can still clean
        // up after itself.
        drawTeardownRef.current()
        map!.setStyle(OSM_RASTER.style as unknown as string)
      })

      map.on('styledata', setupLayers)
      if (map.isStyleLoaded()) setupLayers()
    })()

    return () => {
      cancelled = true
      if (moveTimer.current) clearTimeout(moveTimer.current)
      // Markers and the Popup live outside the map's own node, so `map.remove()`
      // does not take them with it.
      donutsRef.current?.clear()
      donutsRef.current = null
      hoverRef.current?.remove()
      hoverRef.current = null
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
    // Forced: the viewport hasn't moved, but which leads belong in it has.
    if (zoomedIn) loadPoints({ force: true })
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
  useEffect(() => { modeRef.current = mode; recolor(mode) }, [mode, recolor])

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
    // The refresh button means "go and ask again", so it must bypass the cache.
    if (zoomedIn) loadPoints({ force: true })
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
        style={{ ...fieldStyle(isMobile), width: 120 }}
      />
      <select value={status} onChange={e => setStatus(e.target.value)}
        style={fieldStyle(isMobile)}>
        <option value="">All statuses</option>
        {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
      </select>
      {mode === 'signals' && (
        <select value={signalDays} onChange={e => setSignalDays(Number(e.target.value))}
          style={fieldStyle(isMobile)}>
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
        style={overlayBtn(heatmap, isMobile)}
      >
        <Grid3x3 size={13} strokeWidth={1.5} /> Heatmap
      </button>
      {heatmap && (
        <select value={heatMetric} onChange={e => setHeatMetric(e.target.value as HeatmapMetric)}
          style={fieldStyle(isMobile)}>
          <option value="density">Customer density</option>
          <option value="avg_score">Avg score</option>
        </select>
      )}
      <button
        onClick={() => { if (showClusters) setSelectedCluster(null); setShowClusters(v => !v) }}
        title="Toggle customer clusters"
        style={overlayBtn(showClusters, isMobile)}
      >
        <Sparkles size={13} strokeWidth={1.5} /> Clusters
      </button>
      <button
        onClick={() => setShowEvents(v => !v)}
        title="Toggle event polygons (hail swaths, new construction, …)"
        style={overlayBtn(showEvents, isMobile)}
      >
        <Zap size={13} strokeWidth={1.5} /> Events
      </button>

      {/* Draw tools. Three endpoints that shipped with no way to reach them:
          the service-area polygon, the event layer, and /geo/prospect's
          lat/lng seed. */}
      <DrawToolbar tool={drawTools.tool} onPick={drawTools.start} touch={isMobile} />
    </>
  )

  return (
    <div style={{ height: '100dvh', display: 'flex', flexDirection: 'column' }}>
      <header style={{
        // Fixed height on mobile, not minHeight: paired with flexWrap this used
        // to grow to two or three rows at 320px and take that height straight
        // out of the map — the opposite of what a phone needs. Filters live in
        // the sheet now, so the row has little enough in it to stay on one line.
        height: isMobile ? 52 : undefined,
        minHeight: isMobile ? undefined : 64,
        padding: isMobile ? '8px 12px' : '0 16px',
        display: 'flex', alignItems: 'center', gap: isMobile ? 8 : 10,
        borderBottom: '1px solid var(--color-ink-200)', background: 'var(--color-paper)', flexShrink: 0,
        flexWrap: isMobile ? 'nowrap' : 'wrap',
        overflow: isMobile ? 'hidden' : undefined,
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
          onClick={togglePlacePicker}
          title="Jump to a ZIP, address, or lead"
          aria-label="Jump to a ZIP, address, or lead"
          aria-expanded={zipOpen}
          aria-haspopup="listbox"
          style={overlayBtn(zipOpen || activeZip != null, isMobile)}
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
            style={{ ...overlayBtn(showControls || activeOverlays > 0, true), position: 'relative' }}
          >
            <SlidersHorizontal size={13} strokeWidth={1.5} /> Filters
            {activeOverlays > 0 && !showControls && ` · ${activeOverlays}`}
          </button>
        )}
        <button onClick={refresh} className="dash-icon-btn" title="Refresh">
          <RefreshCw size={13} strokeWidth={1.5} className={loading ? 'animate-spin' : ''} />
        </button>
      </header>

      {/* Mobile: filters and overlays in a bottom sheet.
          Previously a static block in this flex column, so opening it *took
          height away from the map* — the opposite of what a phone needs. The
          sheet floats over the map instead, and peeks at 45% so a rep can see
          both the controls and where they are. */}
      {isMobile && (
        <Sheet
          open={showControls}
          onClose={() => setShowControls(false)}
          label="Filters and overlays"
          title="Filters & overlays"
          snapPoints={[0.45, 0.85]}
        >
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 }}>
            {filterControls}
          </div>
        </Sheet>
      )}

      <div style={{ flex: 1, position: 'relative', minHeight: 0 }}>
        <div ref={containerRef} style={{ position: 'absolute', inset: 0 }} />
        {glUnsupported && <UnsupportedDevice />}
        {!glUnsupported && <Legend key={isMobile ? 'mobile' : 'desktop'} mode={mode} collapsible={isMobile} />}
        {!glUnsupported && truncated && zoomedIn && (
          <TruncationNotice limit={PIN_LIMIT} isMobile={isMobile} />
        )}
        {/* Two stacked pills 34px apart is noise. The truncation notice is the
            more important message — "you're only seeing part of the data"
            outranks "zoom out for blocks" — so the hint yields to it. */}
        {isMobile && !glUnsupported && !truncated && (
          <span style={{
            // z-index declared, and the pill yields to the truncation notice:
            // "you're only seeing part of the data" outranks "zoom out for
            // blocks". They sit 34px apart and used to stack silently.
            position: 'absolute', top: 10, left: '50%', transform: 'translateX(-50%)', zIndex: 2,
            fontSize: 11, color: 'var(--color-ink-700)', background: 'var(--color-paper)',
            border: '1px solid var(--color-ink-200)', borderRadius: 'var(--radius-pill)',
            padding: '3px 10px', boxShadow: 'var(--shadow-card)', pointerEvents: 'none', whiteSpace: 'nowrap',
          }}>
            {zoomedIn ? 'Properties · zoom out for blocks' : 'Regions · zoom in for pins'}
          </span>
        )}
        {zipOpen && (
          <PlacePicker
            zips={zips}
            zipsLoading={zipsLoading}
            query={zipQuery}
            onQuery={setZipQuery}
            onPickZip={jumpToZip}
            leads={leadSearchArmed ? leadHits : []}
            leadsLoading={leadSearchArmed && leadsLoading}
            onPickLead={jumpToLead}
            onClose={() => setZipOpen(false)}
            isMobile={isMobile}
            areaLabel={serviceAreaLabel()}
          />
        )}
        {showClusters && selectedCluster && !drawTools.tool && (
          <ClusterActionPanel
            cluster={selectedCluster}
            busy={prospecting}
            onProspect={() => handleProspect(selectedCluster.label)}
            onClose={() => setSelectedCluster(null)}
          />
        )}
        {drawTools.tool && !drawTools.pending && (
          <DrawHint tool={drawTools.tool} onCancel={drawTools.cancel} />
        )}
        {/* Blast radius. Mutually exclusive with the draw panels — they share the
            bottom-centre slot, and a draw session clears the overlay anyway. */}
        {!drawTools.tool && blast && (
          <BlastPanel
            address={blast.lead.address ?? ''}
            hits={blast.hits}
            radiusM={blast.radius}
            onPick={openLead}
            onClose={clearBlast}
          />
        )}
        {drawTools.pending && (
          <DrawConfirm
            pending={drawTools.pending}
            busy={savingDraw}
            onSave={saveDrawing}
            onRedraw={drawTools.redraw}
            onCancel={drawTools.cancel}
          />
        )}
      </div>

      <ContactDrawer
        lead={selectedLead}
        // "Show neighbors" belongs to the lead being viewed, so it renders in
        // the drawer rather than floating over a map the drawer covers.
        actions={l => (
          l.status === 'won' && l.latitude != null && l.longitude != null
            ? <NeighborsPrompt busy={blastLoading} onShow={() => showNeighbors(l)} />
            : null
        )}
        onClose={() => { setSelectedLead(null); setActivePin(null) }}
        onStatusChange={() => refresh()}
        onLeadChange={updated => { setSelectedLead(updated); refresh() }}
        onToast={showToast}
      />
      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </div>
  )
}

export function PropertyMap() {
  return <AuthGuard><PropertyMapInner /></AuthGuard>
}
