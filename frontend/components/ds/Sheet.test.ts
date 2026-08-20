import { describe, it, expect } from 'vitest'
import { resolveDrag, DISMISS_DISTANCE, DISMISS_VELOCITY } from './Sheet'

/**
 * The drag gesture is new to this app — there was no swipe or snap logic
 * anywhere before it. Its failures are quiet: a sheet that dismisses on a small
 * nudge, or one that can't be dismissed at all, reads as "janky" rather than as
 * a bug with a line number. So the decision itself is pinned here.
 *
 * Two snaps (peek / full) is the map's configuration; index 0 is the lowest.
 */
const SNAPS = 2

describe('resolveDrag', () => {
  it('ignores a small downward nudge', () => {
    expect(resolveDrag(20, 0, 0, SNAPS)).toEqual({ kind: 'stay' })
  })

  it('dismisses a long downward drag from the lowest snap', () => {
    expect(resolveDrag(DISMISS_DISTANCE + 1, 0, 0, SNAPS)).toEqual({ kind: 'dismiss' })
  })

  it('steps down rather than dismissing when a taller snap is available', () => {
    // The gesture must be reversible: dragging down from "full" goes to "peek",
    // not straight to gone.
    expect(resolveDrag(DISMISS_DISTANCE + 1, 0, 1, SNAPS)).toEqual({ kind: 'snap', index: 0 })
  })

  it('dismisses on a downward flick regardless of distance', () => {
    // A fast short flick is the natural "get rid of this" gesture; requiring
    // distance as well would make it feel unresponsive.
    expect(resolveDrag(10, DISMISS_VELOCITY + 0.1, 0, SNAPS)).toEqual({ kind: 'dismiss' })
  })

  it('does not dismiss on an upward flick', () => {
    // Velocity is signed; a fast upward drag must never be read as a dismissal.
    expect(resolveDrag(-10, -2, 0, SNAPS).kind).not.toBe('dismiss')
  })

  it('expands on an upward drag, with a lower bar than dismissal', () => {
    // Expanding is cheap to undo, dismissing isn't — so upward needs half the
    // travel.
    expect(resolveDrag(-(DISMISS_DISTANCE / 2) - 1, 0, 0, SNAPS)).toEqual({ kind: 'snap', index: 1 })
    expect(resolveDrag(-10, 0, 0, SNAPS)).toEqual({ kind: 'stay' })
  })

  it('stays put when already at the tallest snap and dragged up', () => {
    expect(resolveDrag(-200, 0, SNAPS - 1, SNAPS)).toEqual({ kind: 'stay' })
  })

  it('handles a single-snap sheet — down dismisses, up does nothing', () => {
    expect(resolveDrag(DISMISS_DISTANCE + 1, 0, 0, 1)).toEqual({ kind: 'dismiss' })
    expect(resolveDrag(-200, 0, 0, 1)).toEqual({ kind: 'stay' })
  })

  it('treats exactly-threshold movement as not yet enough', () => {
    // Boundary: the comparison is strict, so the threshold itself stays put.
    expect(resolveDrag(DISMISS_DISTANCE, 0, 0, SNAPS)).toEqual({ kind: 'stay' })
  })
})
