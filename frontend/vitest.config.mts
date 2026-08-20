import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'

/**
 * Unit tests for the map's pure logic.
 *
 * Deliberately narrow. This is not a component-testing setup — there is no
 * jsdom, no React Testing Library, and no MapLibre stub, because the modules
 * worth pinning here don't need any of that. `components/map/geojson.ts`,
 * `lib/gradeColors.ts` and `spriteId` in `lib/mapPins.ts` are pure functions:
 * same input, same output, no DOM. That is exactly the split CLAUDE.md
 * prescribes on the backend (api/messaging.py, pipeline/reconcile.py), applied
 * to the frontend.
 *
 * Anything that reads `getComputedStyle` or touches a canvas — `readPalette`,
 * `rasterize` — stays out. Those need a browser, and they're covered by the
 * manual checks instead. If a test here ever needs a DOM, that's a signal the
 * code under test is in the wrong module, not that this config should grow.
 */
export default defineConfig({
  test: {
    include: ['**/*.test.ts'],
    exclude: ['node_modules/**', '.next/**'],
    environment: 'node',
  },
  resolve: {
    alias: {
      // Mirrors the `@/*` path alias in tsconfig.json.
      '@': fileURLToPath(new URL('./', import.meta.url)),
    },
  },
})
