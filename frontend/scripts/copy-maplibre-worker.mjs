/**
 * Copy MapLibre's worker bundle into public/maplibre/.
 *
 * Why this exists: MapLibre v6 loads its worker via
 * `new URL('maplibre-gl/dist/maplibre-gl-worker.mjs', import.meta.url)`. Next's
 * bundlers rewrite that into a hashed asset WITHOUT emitting the worker's
 * `maplibre-gl-shared.mjs` sibling alongside it. The worker then fails on its
 * first import and the map mounts but never requests a tile — no error in the
 * page, nothing in the console, just an empty basemap. It reproduces in
 * `next build` (both Turbopack and --webpack) and not in `next dev`, which is
 * what makes it dangerous.
 *
 * Serving both files ourselves from /public sidesteps the bundler entirely.
 * PropertyMap pairs this with `setWorkerUrl('/maplibre/maplibre-gl-worker.mjs')`.
 *
 * Wired to `prebuild`/`predev`, NOT `postinstall`: package managers skip
 * lifecycle scripts when an install has no work to do, so a warm CI cache would
 * silently ship without the worker.
 */
import { copyFileSync, mkdirSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'

// Both files are required. The worker imports the shared chunk on startup;
// copying only the worker reproduces the exact bug this script prevents.
const FILES = ['maplibre-gl-worker.mjs', 'maplibre-gl-shared.mjs']

const require = createRequire(import.meta.url)
const dist = dirname(require.resolve('maplibre-gl/package.json')) + '/dist'
const out = join(process.cwd(), 'public', 'maplibre')

mkdirSync(out, { recursive: true })
for (const f of FILES) {
  copyFileSync(join(dist, f), join(out, f))
}
console.log(`[maplibre] copied ${FILES.length} worker file(s) to public/maplibre/`)
