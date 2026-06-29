'use client'
import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Pointer-Events based drag controller for the pipeline board.
 *
 * Replaces the native HTML5 drag-and-drop API, which has two problems:
 *   - it doesn't work on touch devices at all, and
 *   - highlighting the hovered column on every `dragover` event re-renders the
 *     whole board, which makes desktop dragging laggy.
 *
 * This hook handles mouse + touch uniformly via Pointer Events and moves the
 * floating "ghost" with a direct DOM transform (no React render per frame), so
 * it stays smooth even with many cards. Column-highlight state only updates
 * when the hovered column actually changes.
 *
 * All imperative logic lives in a single mount effect so the document-level
 * listeners keep a stable identity (and always detach cleanly), while still
 * reading the latest props/state through refs.
 */

// Mouse: start dragging once the pointer moves past this many px (so a plain
// click still selects). Touch: a tap that moves less than this stays a tap.
const MOUSE_DRAG_THRESHOLD = 5
const TOUCH_SLOP = 12
// Touch needs a press-and-hold before grabbing a card, otherwise a quick swipe
// to scroll the board would pick up a card instead.
const LONG_PRESS_MS = 180
// Auto-scroll the board when the pointer nears its horizontal edges.
const EDGE_ZONE = 60
const EDGE_SPEED = 14

interface Options<T> {
  /** Stable id for an item (used to dim the source card while dragging). */
  getId: (item: T) => number | string
  /** Current stage/column key of an item. */
  getStage: (item: T) => string
  /** Fired on drop when the item lands on a different column. */
  onDrop: (item: T, toStage: string) => void
  /** Fired on a tap/click that wasn't a drag. */
  onSelect?: (item: T) => void
  /** The horizontally-scrolling board container, for edge auto-scroll. */
  scrollRef: React.RefObject<HTMLElement | null>
}

export function useKanbanDnd<T>(options: Options<T>) {
  // Render state — intentionally coarse-grained so the board doesn't re-render
  // on every pointer move.
  const [dragItem, setDragItem] = useState<T | null>(null)
  const [overStage, setOverStage] = useState<string | null>(null)

  // Latest props, so the (stable) listeners never go stale.
  const optsRef = useRef(options)
  useEffect(() => { optsRef.current = options })

  const ghostRef = useRef<HTMLDivElement | null>(null)
  const stateRef = useRef({
    pendingItem: null as T | null,
    pointerId: -1,
    isTouch: false,
    startX: 0,
    startY: 0,
    pointerX: 0,
    pointerY: 0,
    activated: false,
    overStage: null as string | null,
    longPress: 0 as ReturnType<typeof setTimeout> | 0,
    raf: 0,
    autoScrollDir: 0,
  })

  // Imperative entry point, wired up by the mount effect below.
  const api = useRef<{ onPointerDown: (e: React.PointerEvent, item: T) => void }>({
    onPointerDown: () => {},
  })

  useEffect(() => {
    const s = stateRef.current

    function positionGhost() {
      const g = ghostRef.current
      if (g) g.style.transform = `translate(${s.pointerX}px, ${s.pointerY}px) rotate(2deg)`
    }

    function updateOverStage() {
      const el = document.elementFromPoint(s.pointerX, s.pointerY)
      const key = el?.closest('[data-stage-key]')?.getAttribute('data-stage-key') ?? null
      if (key !== s.overStage) {
        s.overStage = key
        setOverStage(key)
      }
    }

    function runAutoScroll() {
      const el = optsRef.current.scrollRef.current
      if (el && s.autoScrollDir !== 0) el.scrollLeft += s.autoScrollDir
      s.raf = s.autoScrollDir !== 0 ? requestAnimationFrame(runAutoScroll) : 0
    }

    function updateAutoScroll() {
      const el = optsRef.current.scrollRef.current
      if (!el) return
      const r = el.getBoundingClientRect()
      let dir = 0
      if (s.pointerX < r.left + EDGE_ZONE) dir = -EDGE_SPEED
      else if (s.pointerX > r.right - EDGE_ZONE) dir = EDGE_SPEED
      s.autoScrollDir = dir
      if (dir !== 0 && s.raf === 0) s.raf = requestAnimationFrame(runAutoScroll)
    }

    function activate() {
      if (s.activated || !s.pendingItem) return
      if (s.longPress) { clearTimeout(s.longPress); s.longPress = 0 }
      s.activated = true
      setDragItem(s.pendingItem)
      updateOverStage()
      if (s.isTouch && typeof navigator !== 'undefined' && navigator.vibrate) navigator.vibrate(8)
    }

    function cleanup() {
      document.removeEventListener('pointermove', onPointerMove)
      document.removeEventListener('pointerup', onPointerUp)
      document.removeEventListener('pointercancel', onPointerUp)
      document.removeEventListener('touchmove', onTouchMove)
      if (s.longPress) { clearTimeout(s.longPress); s.longPress = 0 }
      if (s.raf) { cancelAnimationFrame(s.raf); s.raf = 0 }
      s.autoScrollDir = 0
    }

    function onTouchMove(e: TouchEvent) {
      // While actively dragging, stop the browser from scrolling the board.
      if (s.activated && e.cancelable) e.preventDefault()
    }

    function onPointerMove(e: PointerEvent) {
      if (e.pointerId !== s.pointerId) return
      s.pointerX = e.clientX
      s.pointerY = e.clientY
      const dist = Math.hypot(e.clientX - s.startX, e.clientY - s.startY)

      if (!s.activated) {
        if (s.isTouch) {
          // Moved before the long-press fired → treat as a scroll, not a drag.
          if (dist > TOUCH_SLOP) cleanup()
        } else if (dist > MOUSE_DRAG_THRESHOLD) {
          activate()
        }
        if (!s.activated) return
      }

      positionGhost()
      updateOverStage()
      updateAutoScroll()
    }

    function onPointerUp(e: PointerEvent) {
      if (e.pointerId !== s.pointerId) return
      const item = s.pendingItem
      const wasDrag = s.activated
      const toStage = s.overStage
      cleanup()
      s.pendingItem = null
      s.pointerId = -1
      s.activated = false
      s.overStage = null
      setDragItem(null)
      setOverStage(null)

      if (item && wasDrag) {
        if (toStage && optsRef.current.getStage(item) !== toStage) optsRef.current.onDrop(item, toStage)
      } else if (item) {
        optsRef.current.onSelect?.(item)
      }
    }

    function onPointerDown(e: React.PointerEvent, item: T) {
      // Ignore drags that start on an interactive control (e.g. the quick-task +).
      if ((e.target as HTMLElement).closest('[data-no-drag]')) return
      if (e.pointerType === 'mouse' && e.button !== 0) return

      s.pendingItem = item
      s.pointerId = e.pointerId
      s.isTouch = e.pointerType === 'touch'
      s.startX = s.pointerX = e.clientX
      s.startY = s.pointerY = e.clientY
      s.activated = false
      s.overStage = optsRef.current.getStage(item)

      document.addEventListener('pointermove', onPointerMove)
      document.addEventListener('pointerup', onPointerUp)
      document.addEventListener('pointercancel', onPointerUp)
      if (s.isTouch) {
        document.addEventListener('touchmove', onTouchMove, { passive: false })
        s.longPress = setTimeout(activate, LONG_PRESS_MS)
      }
    }

    api.current.onPointerDown = onPointerDown
    return cleanup
  }, [])

  const onPointerDown = useCallback((e: React.PointerEvent, item: T) => {
    api.current.onPointerDown(e, item)
  }, [])

  // Position the ghost the instant it mounts so it doesn't flash at (0,0).
  const setGhostNode = useCallback((node: HTMLDivElement | null) => {
    ghostRef.current = node
    if (node) {
      const s = stateRef.current
      node.style.transform = `translate(${s.pointerX}px, ${s.pointerY}px) rotate(2deg)`
    }
  }, [])

  const draggingId = dragItem != null ? options.getId(dragItem) : null

  return { dragItem, draggingId, overStage, onPointerDown, setGhostNode }
}
