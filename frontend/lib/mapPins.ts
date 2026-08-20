/**
 * Branded map pins, drawn from the Axon mark.
 *
 * The map used to render every property as a 6px colored dot, which carried the
 * grade and nothing else — no shape, no glyph, no state. These are real pins:
 * the grade letter is legible at pin zoom, recent intent signals get a badge,
 * and the whole thing is keyed to the design system's tokens.
 *
 * ## Why pre-rendered images rather than SDF
 *
 * MapLibre can recolor an icon at runtime via `icon-color` if the image is
 * registered as a signed distance field (`{sdf: true}`). We deliberately don't:
 *
 *   • SDF is single-color. These pins have a slate body, a grade-colored
 *     border, and a light letter — three colors, so SDF can't express them.
 *   • SDF is measurably softer; MapLibre's maintainers describe the loss of
 *     sharpness as inherent to the technique.
 *   • Rasterized-SVG alpha is *not* a distance field. Passing `{sdf: true}`
 *     with a canvas rasterization renders, but the edges are wrong, because a
 *     real SDF encodes signed distance to the nearest edge, not coverage.
 *
 * The palette here is small and discrete — four grades plus two signal states —
 * so a fixed sprite set costs nothing at runtime and buys full artistic
 * control. Sprites are generated from the live CSS custom properties, which
 * keeps the "map colors come from the design system" property intact: change a
 * token and the pins follow.
 *
 * ## Why a diamond
 *
 * `components/ds/Logo.tsx` draws the Axon mark as a diamond
 * (`polygon points="16,5 27,16 16,27 5,16"`). A diamond's lower vertex is a
 * natural map anchor, so the brand mark *is* the pin shape rather than a
 * generic teardrop with a logo bolted on. The tradeoff is real: a diamond
 * wastes its corners, so the letter has less usable interior than it would in a
 * circle. That's why the body is drawn slightly taller than wide and the letter
 * sits above the point rather than centred in the bounding box.
 */

export type PinGrade = 'A' | 'B' | 'C' | 'D' | 'S' | 'N'

/** Every sprite the map registers. Grades, plus the two signals-mode states. */
export const PIN_GRADES: PinGrade[] = ['A', 'B', 'C', 'D', 'S', 'N']

/** Stable sprite id for a (grade, signal) pair. Must match what layers request. */
export function spriteId(grade: string, hasSignal: boolean): string {
  const g = PIN_GRADES.includes(grade as PinGrade) ? grade : 'N'
  return `pin-${g}${hasSignal ? '-sig' : ''}`
}

/** Logical pin size in CSS pixels, before devicePixelRatio scaling. */
const W = 30
const H = 38

/**
 * One pin, as an SVG string.
 *
 * Drawn in a `W x H` box with the diamond's lower vertex at the bottom-centre,
 * so `icon-anchor: 'bottom'` puts the point exactly on the coordinate.
 */
function pinSvg(opts: {
  accent: string       // grade color — border + letter tint
  body: string         // slate body fill
  ink: string          // letter color
  letter: string       // '' for the signals-mode states
  signal: string | null // badge color, or null for no badge
}): string {
  const { accent, body, ink, letter, signal } = opts
  const cx = W / 2
  // Diamond: top, right, bottom point, left.
  const pts = `${cx},2 ${W - 3},${cx + 1} ${cx},${H - 2} 3,${cx + 1}`
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
  <polygon points="${pts}" fill="${body}" stroke="${accent}" stroke-width="2.5" stroke-linejoin="round"/>
  <polygon points="${pts}" fill="${accent}" fill-opacity="0.22"/>
  ${letter
    ? `<text x="${cx}" y="${cx + 5}" text-anchor="middle" font-family="Roboto Slab, Georgia, serif"
         font-size="13" font-weight="600" fill="${ink}">${letter}</text>`
    : `<circle cx="${cx}" cy="${cx + 1}" r="3.2" fill="${ink}"/>`}
  ${signal ? `<circle cx="${W - 6}" cy="7" r="4.5" fill="${signal}" stroke="${body}" stroke-width="1.5"/>` : ''}
</svg>`
}

/**
 * Rasterize an SVG string into ImageData at `dpr`.
 *
 * Two things that bite here: an `<img>` fed a data-URI SVG with no intrinsic
 * size decodes to 0x0 in some browsers unless width/height are set explicitly,
 * and the dpr must be handed to `addImage` as `pixelRatio` or the art renders
 * at its pixel size rather than its intended CSS size.
 */
function rasterize(svg: string, dpr: number): Promise<ImageData> {
  return new Promise((resolve, reject) => {
    const img = new Image(W * dpr, H * dpr)
    img.onload = () => {
      const c = document.createElement('canvas')
      c.width = W * dpr
      c.height = H * dpr
      const ctx = c.getContext('2d')
      if (!ctx) return reject(new Error('2d context unavailable'))
      ctx.drawImage(img, 0, 0, W * dpr, H * dpr)
      resolve(ctx.getImageData(0, 0, c.width, c.height))
    }
    img.onerror = () => reject(new Error('pin SVG failed to rasterize'))
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
  })
}

export interface PinPalette {
  gradeA: string; gradeB: string; gradeC: string; gradeD: string
  body: string; ink: string; neutral: string; signal: string
}

/** Border/letter color per sprite grade. */
function accentFor(g: PinGrade, p: PinPalette): string {
  switch (g) {
    case 'A': return p.gradeA
    case 'B': return p.gradeB
    case 'C': return p.gradeC
    case 'D': return p.gradeD
    case 'S': return p.signal   // signals mode: has recent signals
    default:  return p.neutral  // signals mode: none, or unknown grade
  }
}

/** The letter drawn in the body. Signals-mode sprites use a dot instead. */
function letterFor(g: PinGrade): string {
  return g === 'S' || g === 'N' ? '' : g
}

/**
 * Register every pin sprite on the map.
 *
 * Idempotent — safe to call again after a style swap, which drops all images
 * along with the layers. `pixelRatio` is capped at 2: 3x costs 2.25x the atlas
 * memory of 2x for no perceptible gain at this size.
 */
export async function registerPinSprites(
  map: { hasImage: (id: string) => boolean; addImage: (id: string, img: ImageData, opts?: { pixelRatio?: number }) => void },
  palette: PinPalette,
): Promise<void> {
  const dpr = Math.min(typeof window === 'undefined' ? 1 : window.devicePixelRatio || 1, 2)
  await Promise.all(
    PIN_GRADES.flatMap(g =>
      [false, true].map(async hasSignal => {
        const id = spriteId(g, hasSignal)
        if (map.hasImage(id)) return
        const svg = pinSvg({
          accent: accentFor(g, palette),
          body: palette.body,
          ink: palette.ink,
          letter: letterFor(g),
          signal: hasSignal ? palette.signal : null,
        })
        try {
          map.addImage(id, await rasterize(svg, dpr), { pixelRatio: dpr })
        } catch (err) {
          // A missing sprite makes its pins invisible, so say which one rather
          // than letting the layer silently drop features.
          console.error(`[map] failed to register pin sprite "${id}"`, err)
        }
      }),
    ),
  )
}
