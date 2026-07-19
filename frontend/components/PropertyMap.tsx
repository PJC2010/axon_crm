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
import { useEffect, useRef, useState, useCallback, useSyncExternalStore, type CSSProperties } from 'react'
import Link from 'next/link'
import { ArrowLeft, Home, RefreshCw, Signal, Award, Grid3x3, Sparkles, Zap, X, SlidersHorizontal, ChevronDown, ChevronUp } from 'lucide-react'
import ngeohash from 'ngeohash'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { Map as MLMap, GeoJSONSource, MapMouseEvent } from 'maplibre-gl'
import { getMapCells, getMapProperties, getLead, getGeoHeatmap, getGeoClusters, prospectArea, getGeoEvents } from '@/lib/api'
import { AuthGuard } from '@/components/AuthGuard'
import { ContactDrawer } from '@/components/ContactDrawer'
import { ToastStack, useToast } from '@/components/Toast'
import type { MapCell, MapPoint, Lead, LeadStatus, HeatmapCell, HeatmapMetric } from '@/lib/types'

type ColorMode = 'signals' | 'score'

// Below this zoom we show the choropleth; at/above it we swap to property pins.
const PIN_ZOOM = 13
// Houston — the app's primary service area (matches the seed/HCAD data).
const HOME: [number, number] = [-95.3698, 29.7604]

const STATUSES: LeadStatus[] = [
  'new', 'contacted', 'qualified', 'quote_sent', 'won', 'lost', 'not_interested', 'converted',
]

// Free, no-key default basemap (OpenStreetMap raster). Override with a provider
// style URL via NEXT_PUBLIC_MAP_STYLE for production-grade tiles + vector glyphs.
const ENV_STYLE = process.env.NEXT_PUBLIC_MAP_STYLE
const OSM_STYLE = {
  version: 8 as const,
  glyphs: 'https://fonts.openmaptiles.org/{fontstack}/{range}.pbf',
  sources: {
    osm: {
      type: 'raster' as const,
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution: '© OpenStreetMap contributors',
    },
  },
  layers: [{ id: 'osm', type: 'raster' as const, source: 'osm' }],
}

// Resolve design-system CSS variables to concrete hex (WebGL can't read vars).
function readPalette() {
  const cs = getComputedStyle(document.documentElement)
  const v = (name: string, fallback: string) => cs.getPropertyValue(name).trim() || fallback
  return {
    none:   v('--color-ink-200', '#e5e7eb'),
    cool:   v('--color-ocean',   '#3b82f6'),
    moss:   v('--color-moss',    '#16a34a'),
    accent: v('--color-accent',  '#65a30d'),
    gold:   v('--color-gold',    '#d97706'),
    danger: v('--color-danger',  '#dc2626'),
    line:   v('--color-ink-300', '#cbd5e1'),
  }
}
type Palette = ReturnType<typeof readPalette>

// ── color logic (shared by cells + pins) ─────────────────────────────────────────

function cellColor(c: MapCell, mode: ColorMode, p: Palette): string {
  if (mode === 'signals') {
    if (c.signal_count <= 0) return p.none
    if (c.signal_count <= 2) return p.gold
    if (c.signal_count <= 5) return p.accent === p.gold ? p.danger : p.gold
    return p.danger
  }
  // score: shade by the cell's average lead score (higher = better prospect)
  const s = c.avg_score
  if (s == null) return p.none
  if (s >= 80) return p.moss
  if (s >= 65) return p.accent
  if (s >= 50) return p.gold
  return p.danger
}

function pointColor(pt: MapPoint, mode: ColorMode, p: Palette): string {
  if (mode === 'signals') return pt.signals.length > 0 ? p.danger : p.cool
  switch (pt.score_grade) {
    case 'A': return p.moss
    case 'B': return p.accent
    case 'C': return p.gold
    case 'D': return p.danger
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

function pointsToGeoJSON(points: MapPoint[], mode: ColorMode, p: Palette) {
  return {
    type: 'FeatureCollection' as const,
    features: points.map(pt => ({
      type: 'Feature' as const,
      properties: {
        id: pt.id,
        address: pt.address ?? '',
        color: pointColor(pt, mode, p),
      },
      geometry: { type: 'Point' as const, coordinates: [pt.longitude, pt.latitude] },
    })),
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
  const { toasts, show: showToast, dismiss: dismissToast } = useToast()
  // Mobile layout: controls collapse behind a Filters button, legend collapses.
  const isMobile = useMediaQuery('(max-width: 767px)')
  const [showControls, setShowControls] = useState(false)

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
      if (!fittedRef.current && cells.length) {
        const lats = cells.map(c => c.lat).filter((x): x is number => x != null)
        const lngs = cells.map(c => c.lng).filter((x): x is number => x != null)
        if (lats.length && lngs.length) {
          map.fitBounds(
            [[Math.min(...lngs), Math.min(...lats)], [Math.max(...lngs), Math.max(...lats)]],
            { padding: 60, maxZoom: 12, duration: 0 },
          )
        }
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

  const openLead = useCallback(async (id: number) => {
    try {
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

    ;(async () => {
      const maplibregl = (await import('maplibre-gl')).default
      if (cancelled || !containerRef.current) return
      paletteRef.current = readPalette()

      map = new maplibregl.Map({
        container: containerRef.current,
        style: (ENV_STYLE as string) || (OSM_STYLE as unknown as string),
        center: HOME,
        zoom: 10,
      })
      mapRef.current = map
      map.addControl(new maplibregl.NavigationControl(), 'top-right')

      // Add our data layers as soon as the *style* is parsed — deliberately NOT
      // on the 'load' event, which also waits for the basemap's first tiles to
      // download. If the tile provider is slow or unreachable, 'load' can never
      // fire, which would silently leave the map with no cells/pins. Gating on
      // the style instead keeps the overlay working regardless of basemap tiles.
      const setupLayers = () => {
        if (!map || !map.isStyleLoaded() || map.getLayer('cell-fill')) return
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
        map.addLayer({
          id: 'cluster-count', type: 'symbol', source: 'points', filter: ['has', 'point_count'],
          layout: { 'text-field': ['get', 'point_count_abbreviated'], 'text-size': 12 },
          paint: { 'text-color': '#ffffff' },
        })
        // Bigger pins on touch devices so they're tappable with a finger.
        const coarsePointer = window.matchMedia('(pointer: coarse)').matches
        map.addLayer({
          id: 'pin', type: 'circle', source: 'points', filter: ['!', ['has', 'point_count']],
          paint: {
            'circle-color': ['get', 'color'], 'circle-radius': coarsePointer ? 9 : 6,
            'circle-stroke-width': 1.5, 'circle-stroke-color': '#ffffff',
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
              0, paletteRef.current!.cool, 0.5, paletteRef.current!.gold, 1, paletteRef.current!.danger],
            'fill-opacity': 0.55,
          },
        })

        // Customer-cluster hulls (Phase 3) — hidden until toggled; click to prospect.
        map.addSource('clusters-hull', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
        map.addLayer({
          id: 'cluster-hull-fill', type: 'fill', source: 'clusters-hull',
          layout: { visibility: 'none' },
          paint: { 'fill-color': paletteRef.current!.moss, 'fill-opacity': 0.12 },
        })
        map.addLayer({
          id: 'cluster-hull-line', type: 'line', source: 'clusters-hull',
          layout: { visibility: 'none' },
          paint: { 'line-color': paletteRef.current!.moss, 'line-width': 2, 'line-dasharray': [2, 1] },
        })

        // Event polygons (Phase 4) — hidden until toggled. Active events shade
        // hot; expired ones fade to the neutral line color.
        map.addSource('events', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
        map.addLayer({
          id: 'event-fill', type: 'fill', source: 'events',
          layout: { visibility: 'none' },
          paint: {
            'fill-color': ['case', ['get', 'active'], paletteRef.current!.danger, paletteRef.current!.line],
            'fill-opacity': 0.18,
          },
        })
        map.addLayer({
          id: 'event-line', type: 'line', source: 'events',
          layout: { visibility: 'none' },
          paint: {
            'line-color': ['case', ['get', 'active'], paletteRef.current!.danger, paletteRef.current!.line],
            'line-width': 2,
          },
        })

        // Interactions
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
        map.on('zoomend', applyZoom)
        map.on('moveend', () => {
          if (moveTimer.current) clearTimeout(moveTimer.current)
          moveTimer.current = setTimeout(() => { if (map && map.getZoom() >= PIN_ZOOM) loadPoints() }, 350)
        })

        applyZoom()
        loadCells()
      }

      // Run now if the style is already parsed, otherwise on each styledata tick
      // until it is. setupLayers is idempotent (guards on cell-fill), so the
      // repeated listener is harmless and self-terminates after the first run.
      if (map.isStyleLoaded()) setupLayers()
      else map.on('styledata', setupLayers)
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
        <Legend key={isMobile ? 'mobile' : 'desktop'} mode={mode} collapsible={isMobile} />
        {isMobile && (
          <span style={{
            position: 'absolute', top: 10, left: '50%', transform: 'translateX(-50%)',
            fontSize: 11, color: 'var(--color-ink-700)', background: 'var(--color-paper)',
            border: '1px solid var(--color-ink-200)', borderRadius: 'var(--radius-pill)',
            padding: '3px 10px', boxShadow: 'var(--shadow-card)', pointerEvents: 'none', whiteSpace: 'nowrap',
          }}>
            {zoomedIn ? 'Properties · zoom out for blocks' : 'Regions · zoom in for pins'}
          </span>
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
        onClose={() => setSelectedLead(null)}
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

function Legend({ mode, collapsible }: { mode: ColorMode; collapsible?: boolean }) {
  // Collapsed by default on mobile so it doesn't cover the map (the parent
  // remounts this via `key` when crossing the breakpoint).
  const [open, setOpen] = useState(!collapsible)
  const items = mode === 'signals'
    ? [
        { c: 'var(--color-danger)', t: 'Hot — recent signals' },
        { c: 'var(--color-gold)',   t: 'Some signal activity' },
        { c: 'var(--color-ink-200)', t: 'No recent signals' },
      ]
    : [
        { c: 'var(--color-moss)',   t: 'A — strong' },
        { c: 'var(--color-accent)', t: 'B' },
        { c: 'var(--color-gold)',   t: 'C' },
        { c: 'var(--color-danger)', t: 'D — weak' },
      ]
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
