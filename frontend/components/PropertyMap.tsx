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
import { ArrowLeft, Home, RefreshCw, Signal, Award } from 'lucide-react'
import ngeohash from 'ngeohash'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { Map as MLMap, GeoJSONSource, MapMouseEvent } from 'maplibre-gl'
import { getMapCells, getMapProperties, getLead } from '@/lib/api'
import { AuthGuard } from '@/components/AuthGuard'
import { ContactDrawer } from '@/components/ContactDrawer'
import { ToastStack, useToast } from '@/components/Toast'
import type { MapCell, MapPoint, Lead, LeadStatus } from '@/lib/types'

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

// ── component ─────────────────────────────────────────────────────────────────────

function PropertyMapInner() {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MLMap | null>(null)
  const paletteRef = useRef<Palette | null>(null)
  const cellsRef = useRef<MapCell[]>([])
  const pointsRef = useRef<MapPoint[]>([])
  const fittedRef = useRef(false)
  const moveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const [mode, setMode] = useState<ColorMode>('signals')
  const [vertical, setVertical] = useState('')
  const [status, setStatus] = useState('')
  const [signalDays, setSignalDays] = useState(90)
  const [loading, setLoading] = useState(false)
  const [zoomedIn, setZoomedIn] = useState(false)
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null)
  const { toasts, show: showToast, dismiss: dismissToast } = useToast()

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

      map.on('load', () => {
        if (!map) return
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
        map.addLayer({
          id: 'pin', type: 'circle', source: 'points', filter: ['!', ['has', 'point_count']],
          paint: {
            'circle-color': ['get', 'color'], 'circle-radius': 6,
            'circle-stroke-width': 1.5, 'circle-stroke-color': '#ffffff',
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
        for (const layer of ['pin', 'cell-fill', 'clusters']) {
          map.on('mouseenter', layer, () => { map!.getCanvas().style.cursor = 'pointer' })
          map.on('mouseleave', layer, () => { map!.getCanvas().style.cursor = '' })
        }

        const applyZoom = () => {
          if (!map) return
          const inPins = map.getZoom() >= PIN_ZOOM
          setZoomedIn(inPins)
          const cellVis = inPins ? 'none' : 'visible'
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
      })
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

  const refresh = () => { loadCells(); if (zoomedIn) loadPoints() }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <header style={{
        height: 64, padding: '0 16px', display: 'flex', alignItems: 'center', gap: 10,
        borderBottom: '1px solid var(--color-ink-200)', background: 'var(--color-paper)', flexShrink: 0,
        flexWrap: 'wrap',
      }}>
        <Link href="/dashboard" className="dash-icon-btn" style={{ textDecoration: 'none', color: 'inherit' }}>
          <ArrowLeft size={15} strokeWidth={1.5} />
        </Link>
        <Link href="/home" title="Home" className="dash-icon-btn" style={{ textDecoration: 'none', color: 'inherit' }}>
          <Home size={15} strokeWidth={1.5} />
        </Link>
        <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 600, color: 'var(--color-ink-900)', margin: 0 }}>
          Map
        </h1>

        {/* Color-basis toggle */}
        <div style={{ display: 'flex', gap: 2, background: 'var(--color-ink-100)', borderRadius: 'var(--radius-pill)', padding: 2, marginLeft: 8 }}>
          {([['signals', Signal, 'Intent signals'], ['score', Award, 'Score grade']] as const).map(([key, Icon, label]) => (
            <button
              key={key}
              onClick={() => setMode(key)}
              title={label}
              style={{
                display: 'flex', alignItems: 'center', gap: 5, padding: '5px 12px',
                fontSize: 12, fontWeight: 500, borderRadius: 'var(--radius-pill)', border: 'none', cursor: 'pointer',
                background: mode === key ? 'var(--color-paper)' : 'transparent',
                color: mode === key ? 'var(--color-ink-900)' : 'var(--color-ink-400)',
                boxShadow: mode === key ? 'var(--shadow-card)' : 'none',
              }}
            >
              <Icon size={13} strokeWidth={1.5} /> {label}
            </button>
          ))}
        </div>

        {/* Filters */}
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

        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 11, color: 'var(--color-ink-400)' }}>
          {zoomedIn ? 'Properties' : 'Regions'} · zoom {zoomedIn ? 'out for blocks' : 'in for pins'}
        </span>
        <button onClick={refresh} className="dash-icon-btn" title="Refresh">
          <RefreshCw size={13} strokeWidth={1.5} className={loading ? 'animate-spin' : ''} />
        </button>
      </header>

      <div style={{ flex: 1, position: 'relative', minHeight: 400 }}>
        <div ref={containerRef} style={{ position: 'absolute', inset: 0 }} />
        <Legend mode={mode} />
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

function Legend({ mode }: { mode: ColorMode }) {
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
      <div style={{ fontWeight: 600, marginBottom: 6, color: 'var(--color-ink-900)' }}>
        {mode === 'signals' ? 'Intent signals' : 'Lead score'}
      </div>
      {items.map(i => (
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
