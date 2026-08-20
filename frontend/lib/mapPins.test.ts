import { describe, it, expect } from 'vitest'
import { spriteId, PIN_GRADES } from './mapPins'

/**
 * `spriteId` decides which registered image a pin draws. Get it wrong and the
 * symbol layer asks MapLibre for an image that was never registered, which
 * renders **nothing** — no error, no placeholder, just missing pins. That silent
 * failure mode is why this tiny function is worth pinning.
 */
describe('spriteId', () => {
  it('produces an id for every registered grade, with and without a signal', () => {
    // The contract with registerPinSprites: it registers exactly this set, so
    // anything spriteId can return must be in it.
    const registered = new Set(
      PIN_GRADES.flatMap(g => [spriteId(g, false), spriteId(g, true)]),
    )
    expect(registered.size).toBe(PIN_GRADES.length * 2)
    for (const id of registered) expect(id.startsWith('pin-')).toBe(true)
  })

  it('distinguishes the signal variant', () => {
    expect(spriteId('A', false)).toBe('pin-A')
    expect(spriteId('A', true)).toBe('pin-A-sig')
  })

  it('falls back to the neutral sprite for an unknown grade', () => {
    // A grade the API adds later (or a typo) must land on a sprite that exists
    // rather than producing pin-Q and rendering invisibly.
    expect(spriteId('Q', false)).toBe('pin-N')
    expect(spriteId('', false)).toBe('pin-N')
    expect(spriteId('a', false)).toBe('pin-N')  // case-sensitive by design
  })

  it('covers the two signals-mode pseudo-grades', () => {
    // In signals mode pins split on signal state rather than grade, so S and N
    // are real sprite keys, not fallbacks.
    expect(PIN_GRADES).toContain('S')
    expect(PIN_GRADES).toContain('N')
    expect(spriteId('S', true)).toBe('pin-S-sig')
  })
})
