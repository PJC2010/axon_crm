/**
 * Basemap style resolution for the property map.
 *
 * Two problems this solves, one of them not cosmetic:
 *
 * 1. **Tile policy.** The map used to hardcode raster tiles from
 *    `tile.openstreetmap.org`. The OSM Foundation's usage policy prohibits
 *    heavy and commercial use of that endpoint, and a browser app cannot send
 *    the custom `User-Agent` the policy asks for. Axon is a paid,
 *    multi-tenant product, so it needed its own tile source.
 * 2. **The map didn't match the app.** Axon's design system is dark (slate
 *    `--color-paper` #252a31, turquoise accent). A bright beige raster basemap
 *    under dark chrome reads as a bug.
 *
 * ## Choosing a source
 *
 * Set `NEXT_PUBLIC_MAP_STYLE` to any MapLibre style URL and it wins. Options,
 * cheapest first:
 *
 *   • **Self-hosted PMTiles** (recommended at scale) — a single `.pmtiles`
 *     archive on Cloudflare R2 behind a Worker. Flat ~$5/mo at any volume,
 *     because it is storage plus a Worker rather than metered tile requests.
 *     Set `NEXT_PUBLIC_MAP_STYLE` to a style whose source URL begins
 *     `pmtiles://` and the protocol is registered automatically (see
 *     `registerPmtilesProtocol`).
 *   • **OpenFreeMap** (the default below) — free, no API key, commercial use
 *     explicitly permitted. No SLA; it is community-funded. Good enough to
 *     ship on and to develop against, and it costs nothing to move off.
 *   • **Stadia / MapTiler** — paid, contracted, with an SLA. Note MapTiler's
 *     session pricing requires MapTiler's own SDK; with plain MapLibre you are
 *     billed per request, which gets expensive fast at high pan/zoom volume.
 *
 * ## Why the font stack lives here
 *
 * Every basemap serves its own glyph endpoint with its own fontstack names,
 * and MapLibre requests *exactly* the names a layer asks for. Our clustered
 * count layer needs a font that the active style's glyph server actually has:
 * OpenFreeMap serves `Noto Sans Regular` and 404s on `Open Sans Regular`,
 * while `fonts.openmaptiles.org` (used by the raster fallback) is the reverse.
 * A mismatch fails *silently* — the labels just don't draw — so the font name
 * travels with the style rather than being hardcoded at the layer.
 *
 * That endpoint has bitten this codebase before in a nastier way: it answers
 * unknown fontstacks with an HTML error page under HTTP 200, which MapLibre
 * hands to the protobuf decoder, producing `Unimplemented type: 4`.
 */

/** A basemap choice: the style MapLibre loads, plus the fontstack it can serve. */
export interface BasemapStyle {
  /** Style URL, or an inline MapLibre style object. */
  style: string | object
  /** A fontstack the style's glyph endpoint is known to serve. */
  font: string
  /** Shown in dev logs / diagnostics so it's obvious which source is live. */
  label: string
}

/**
 * Last-resort fallback: raster OpenStreetMap.
 *
 * Deliberately kept, and deliberately not the default. It needs no key and no
 * network configuration, which makes it the right thing to fall back to when a
 * provider is unreachable and the right thing to develop against offline — and
 * it is what makes the "map still renders when the tile host is dead" check
 * meaningful. It must not be what production serves; see the policy note above.
 */
const OSM_RASTER: BasemapStyle = {
  label: 'OpenStreetMap raster (fallback)',
  font: 'Open Sans Regular',
  style: {
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
  },
}

/**
 * Default: OpenFreeMap's dark vector style.
 *
 * Vector rather than raster, so it stays sharp on retina, restyles client-side,
 * and sends far fewer bytes over a phone's 4G — which matters, because reps use
 * this map in a truck. It also serves its own glyphs and sprites, so we no
 * longer depend on `fonts.openmaptiles.org` at all.
 */
const OPENFREEMAP_DARK: BasemapStyle = {
  label: 'OpenFreeMap dark (vector)',
  font: 'Noto Sans Regular',
  style: 'https://tiles.openfreemap.org/styles/dark',
}

/**
 * The fontstack to assume for an operator-supplied style.
 *
 * Override with `NEXT_PUBLIC_MAP_FONT` when pointing at a provider whose glyph
 * endpoint doesn't serve this. Getting it wrong costs the cluster-count labels
 * and nothing else, but it fails silently, so it is worth setting explicitly.
 */
const ENV_STYLE = process.env.NEXT_PUBLIC_MAP_STYLE
const ENV_FONT = process.env.NEXT_PUBLIC_MAP_FONT

export function resolveBasemap(): BasemapStyle {
  if (ENV_STYLE) {
    return {
      label: `NEXT_PUBLIC_MAP_STYLE (${ENV_STYLE})`,
      font: ENV_FONT || OPENFREEMAP_DARK.font,
      style: ENV_STYLE,
    }
  }
  return OPENFREEMAP_DARK
}

export { OSM_RASTER }

/**
 * Register the `pmtiles://` protocol, but only when something actually uses it.
 *
 * `pmtiles` is ~7.5 KB gzip, and importing it unconditionally would load it for
 * every account regardless of which basemap they're on. Registration is global
 * and must happen once per app lifecycle — not per map mount — so this
 * memoizes.
 */
let pmtilesRegistered: Promise<void> | null = null

export function registerPmtilesProtocol(
  maplibregl: { addProtocol: (name: string, fn: never) => void },
): Promise<void> {
  if (pmtilesRegistered) return pmtilesRegistered
  pmtilesRegistered = import('pmtiles')
    .then(({ Protocol }) => {
      maplibregl.addProtocol('pmtiles', new Protocol().tile as never)
    })
    .catch((err) => {
      // Not fatal: a style that needs pmtiles will fail to load its source and
      // MapLibre reports that through its own error channel. Log so the cause
      // is obvious rather than surfacing as an empty basemap.
      console.error('[map] failed to register pmtiles protocol', err)
    })
  return pmtilesRegistered
}

/** True when the resolved style needs the pmtiles protocol registered first. */
export function needsPmtiles(style: string | object): boolean {
  return typeof style === 'string' && style.includes('pmtiles')
}
