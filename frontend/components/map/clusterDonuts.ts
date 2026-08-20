/**
 * Cluster bubbles that show what's inside them.
 *
 * A cluster used to be a flat blue disc with a count: it told you *how many*
 * leads were hidden and nothing about whether any were worth opening. Twelve
 * A-grade leads and twelve D-grade leads looked identical, which is the one
 * comparison the map exists to make.
 *
 * These render as a donut whose arcs are proportional to the grade mix inside,
 * with the count in the middle — so at a glance a mostly-green cluster reads as
 * worth zooming into and a mostly-red one doesn't.
 *
 * ## Why HTML markers here, when the pins are a symbol layer
 *
 * The pins deliberately avoid `Marker` — 2,000 DOM nodes repositioned every
 * frame is the classic way to make a map janky on a mid-range phone. Clusters
 * are the opposite case: there are only ever a few dozen on screen (that is what
 * clustering *is*), and a proportional multi-segment arc is not expressible as a
 * MapLibre circle paint property. So this is the one place where the DOM wins,
 * and the count stays bounded by construction.
 *
 * The grade tallies come from the source's `clusterProperties`, so Supercluster
 * aggregates them during clustering — no per-frame counting on our side.
 */
import type { Palette } from './mapPalette'

/** Grades tallied per cluster. A–D are score mode; S/N are signals mode. */
export const CLUSTER_GRADES = ['A', 'B', 'C', 'D', 'S', 'N'] as const
type ClusterGrade = (typeof CLUSTER_GRADES)[number]

/**
 * `clusterProperties` for the points source.
 *
 * Each entry sums a 1-or-0 per feature, which is how Supercluster expresses
 * "count the members matching this predicate". Built rather than written out so
 * the key names can't drift from CLUSTER_GRADES.
 */
export function gradeClusterProperties(): Record<string, unknown> {
  return Object.fromEntries(
    CLUSTER_GRADES.map(g => [
      `g${g}`,
      ['+', ['case', ['==', ['get', 'grade'], g], 1, 0]],
    ]),
  )
}

function colorFor(g: ClusterGrade, p: Palette): string {
  switch (g) {
    case 'A': return p.gradeA
    case 'B': return p.gradeB
    case 'C': return p.gradeC
    case 'D': return p.gradeD
    case 'S': return p.gradeC   // signals mode: has recent intent
    default:  return p.neutral  // signals mode: none / ungraded
  }
}

/** Radius for a cluster of `n` members — mirrors the old stepped circle sizing. */
function radiusFor(n: number): number {
  if (n >= 100) return 26
  if (n >= 25) return 21
  return 17
}

interface Segment { grade: ClusterGrade; count: number }

/**
 * Donut as an SVG string.
 *
 * Drawn with `stroke-dasharray` on concentric circles rather than arc paths:
 * one circle per segment, each dashed to show only its share and rotated by the
 * cumulative offset. Fewer trig mistakes than hand-built `A` path commands, and
 * it degrades gracefully — a single-grade cluster is just a full ring.
 */
function donutSvg(segments: Segment[], total: number, p: Palette): string {
  const r = radiusFor(total)
  const thickness = Math.max(4, Math.round(r * 0.3))
  const rr = r - thickness / 2                 // radius of the stroked ring
  const circumference = 2 * Math.PI * rr
  const size = r * 2

  let offset = 0
  const rings = segments.map(s => {
    const frac = s.count / total
    const dash = frac * circumference
    // -90deg so the first segment starts at 12 o'clock.
    const rotation = -90 + (offset / total) * 360
    offset += s.count
    return `<circle cx="${r}" cy="${r}" r="${rr}" fill="none"
      stroke="${colorFor(s.grade, p)}" stroke-width="${thickness}"
      stroke-dasharray="${dash} ${circumference - dash}"
      transform="rotate(${rotation} ${r} ${r})"/>`
  }).join('')

  const label = total >= 1000 ? `${Math.round(total / 100) / 10}k` : String(total)
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
    <circle cx="${r}" cy="${r}" r="${rr - thickness / 2}" fill="${p.body}" fill-opacity="0.92"/>
    ${rings}
    <text x="${r}" y="${r + 4}" text-anchor="middle"
      font-family="Geist, -apple-system, sans-serif" font-size="${r > 20 ? 13 : 11}"
      font-weight="600" fill="${p.ink}">${label}</text>
  </svg>`
}

/**
 * The subset of MapLibre this manager needs.
 *
 * Structural rather than importing `Map`, so this module has no dependency on
 * maplibre-gl at all — it never has to be lazy-imported, and it can be reasoned
 * about (and tested) without a WebGL context. Deliberately omits
 * `querySourceFeatures`' options bag: clusters are picked out in JS below, which
 * avoids coupling to MapLibre's filter-expression types for no benefit.
 */
interface DonutMap {
  querySourceFeatures(id: string): Array<{ properties: Record<string, unknown> | null; geometry: unknown }>
  getSource(id: string): unknown
  getZoom(): number
}

export interface DonutManager {
  /** Rebuild markers from the source's current clusters. Cheap to over-call. */
  refresh(): void
  /** Remove every marker. Call on unmount and before a style swap. */
  clear(): void
}

/**
 * Keep one marker per visible cluster in sync with the source.
 *
 * Markers are keyed by `cluster_id` and reused across refreshes, so panning
 * doesn't churn the DOM. `querySourceFeatures` can return the same cluster from
 * several tiles, hence the dedupe — without it the same donut stacks on itself
 * and the label renders bold from overdraw.
 */
export function createDonutManager(
  map: DonutMap,
  markerFactory: (el: HTMLElement, lngLat: [number, number]) => { remove(): void },
  palette: Palette,
): DonutManager {
  const markers = new Map<number, { marker: { remove(): void }; signature: string }>()

  function clear() {
    for (const { marker } of markers.values()) marker.remove()
    markers.clear()
  }

  function refresh() {
    // No source yet (very early, or mid style-swap) — nothing to draw.
    if (!map.getSource('points')) return clear()

    const seen = new Set<number>()

    for (const f of map.querySourceFeatures('points')) {
      const props = f.properties
      const geom = f.geometry as { type?: string; coordinates?: [number, number] } | null
      // Clusters only — unclustered pins come back from the same query and are
      // drawn by the symbol layer, not by markers.
      if (!props || props.cluster_id == null) continue
      if (geom?.type !== 'Point' || !geom.coordinates) continue

      const id = Number(props.cluster_id)
      if (!Number.isFinite(id) || seen.has(id)) continue
      seen.add(id)

      const total = Number(props.point_count) || 0
      if (total <= 0) continue

      const segments: Segment[] = CLUSTER_GRADES
        .map(g => ({ grade: g, count: Number(props[`g${g}`]) || 0 }))
        .filter(s => s.count > 0)

      // Tallies can be absent if clusterProperties wasn't applied (a stale
      // source after a style swap). Fall back to one neutral ring rather than
      // rendering an empty circle with a count floating in it.
      const drawn = segments.length ? segments : [{ grade: 'N' as ClusterGrade, count: total }]
      const drawnTotal = drawn.reduce((n, s) => n + s.count, 0)

      // Re-render only when the mix actually changed.
      const signature = drawn.map(s => `${s.grade}:${s.count}`).join('|') + `/${total}`
      const existing = markers.get(id)
      if (existing && existing.signature === signature) continue
      existing?.marker.remove()

      const el = document.createElement('div')
      el.style.cursor = 'pointer'
      el.setAttribute('aria-hidden', 'true')  // the pins carry the accessible data
      el.innerHTML = donutSvg(drawn, drawnTotal, palette)
      el.dataset.clusterId = String(id)

      markers.set(id, { marker: markerFactory(el, geom.coordinates), signature })
    }

    // Drop markers whose clusters are gone (panned away, or merged at a new zoom).
    for (const [id, { marker }] of markers) {
      if (!seen.has(id)) {
        marker.remove()
        markers.delete(id)
      }
    }
  }

  return { refresh, clear }
}
