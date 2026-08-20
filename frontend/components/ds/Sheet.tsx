'use client'
import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { X } from 'lucide-react'

/**
 * Bottom sheet — a dismissible surface anchored to the bottom of the viewport.
 *
 * Consolidates a shape the app had already copied five times: `QuoteForm`,
 * `InvoiceForm`, `ExpenseForm`, `InvoiceDetail` and the map's place picker each
 * hand-rolled the same fixed-bottom panel, rounded top corners, safe-area
 * padding and 40×4 grab handle. Those call sites still have their own copies;
 * they can migrate onto this one at leisure. New sheets should start here.
 *
 * Two things this adds that none of them had:
 *
 * **Snap points.** A sheet holding filters wants to be peekable — a rep should
 * see the map *and* the controls without committing the whole screen to one or
 * the other. `snapPoints` are viewport-height fractions, smallest first.
 *
 * **A working grab handle.** In all five existing copies the handle is
 * decorative: it has no pointer handlers at all, so it advertises a gesture the
 * sheet doesn't have. Here it drags — between snap points, and off the bottom to
 * dismiss.
 *
 * Conventions follow `hooks/useKanbanDnd.ts`, the app's only other gesture
 * controller: a movement threshold before engaging, non-passive `touchmove` with
 * `preventDefault` while dragging, `[data-no-drag]` as the opt-out for
 * interactive children, and handlers held in a ref so listeners registered once
 * never close over a stale render.
 *
 * The drag surfaces are the handle and the title row — deliberately not the body,
 * which owns its own scroll and would fight the gesture. So `[data-no-drag]`
 * guards interactive children of *those* rows (the close button), not the body;
 * a call site that widens the drag surface needs it on anything tappable.
 */

/** Movement (px) before a pointer-down becomes a drag rather than a tap. */
export const DRAG_THRESHOLD = 4
/** Downward drag (px) past the lowest snap point that dismisses instead of snapping. */
export const DISMISS_DISTANCE = 90
/** Downward velocity (px/ms) that dismisses regardless of distance — a flick. */
export const DISMISS_VELOCITY = 0.5

export type DragOutcome =
  | { kind: 'dismiss' }
  | { kind: 'snap'; index: number }
  | { kind: 'stay' }

/**
 * What a released drag should do.
 *
 * Split out from the pointer handler because it's the part with the actual
 * decisions in it — and because getting it wrong is quiet: a sheet that
 * dismisses on a small downward nudge, or one that can never be dismissed from
 * its tallest snap, both look like "the gesture is janky" rather than like a
 * bug with a location.
 *
 * `dy` is positive downward, matching clientY.
 */
export function resolveDrag(
  dy: number, velocity: number, index: number, snapCount: number,
): DragOutcome {
  const downward = dy > 0
  const flung = velocity > DISMISS_VELOCITY

  if (downward && (flung || dy > DISMISS_DISTANCE)) {
    // Step down through the snaps first, so the gesture is reversible rather
    // than all-or-nothing — only a drag from the lowest snap dismisses.
    return index > 0 ? { kind: 'snap', index: index - 1 } : { kind: 'dismiss' }
  }
  // Upward needs less travel than downward: expanding is cheap to undo,
  // dismissing isn't.
  if (dy < -DISMISS_DISTANCE / 2 && index < snapCount - 1) {
    return { kind: 'snap', index: index + 1 }
  }
  return { kind: 'stay' }
}

export interface SheetProps {
  open: boolean
  onClose: () => void
  /** Accessible name. Required — a dialog without one is unusable on a screen reader. */
  label: string
  /** Visible heading. Omit for a sheet whose content is self-describing. */
  title?: ReactNode
  /**
   * Heights as fractions of the viewport, smallest first. The sheet opens at
   * `initialSnap` and the handle drags between them.
   */
  snapPoints?: number[]
  initialSnap?: number
  children: ReactNode
  /** Stacking context. Defaults above the map's own overlays (which top out at 6). */
  zIndex?: number
}

export function Sheet({
  open, onClose, label, title,
  snapPoints = [0.5, 0.9],
  initialSnap = 0,
  children,
  zIndex = 60,
}: SheetProps) {
  const snaps = snapPoints.length ? snapPoints : [0.5]
  const [snapIndex, setSnapIndex] = useState(Math.min(initialSnap, snaps.length - 1))
  // Live finger offset in px while dragging; null when idle. Kept in state
  // rather than a ref because the transform has to re-render to follow it.
  const [dragY, setDragY] = useState<number | null>(null)
  const sheetRef = useRef<HTMLDivElement>(null)
  const titleId = useId()

  // Reset to the opening snap each time it opens, so a sheet dismissed from the
  // top doesn't reopen there.
  //
  // Adjusted during render off a stored previous value rather than in an effect:
  // an effect would render once at the stale snap and then again at the right
  // one, which is visible as a jump on open.
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) setSnapIndex(Math.min(initialSnap, snaps.length - 1))
  }

  // `onClose` is almost always an inline arrow at the call site, so it has a new
  // identity every parent render. Read it through a ref rather than depending on
  // it: the drag effect below registers document listeners, and re-running it
  // mid-gesture would remove them and kill the drag silently. Same discipline as
  // the map's own `loadPointsRef`.
  const onCloseRef = useRef(onClose)
  useEffect(() => { onCloseRef.current = onClose })

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onCloseRef.current() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  // ── drag ──────────────────────────────────────────────────────────────────
  //
  // Held in a ref object and wired up by a mount effect, so the document-level
  // listeners registered on pointerdown always call the current handlers.
  const api = useRef<{ onPointerDown: (e: React.PointerEvent) => void }>({ onPointerDown: () => {} })

  // Mirrors read by those once-registered handlers. Declared before the effect
  // that closes over them so the ordering is obvious rather than merely legal,
  // and updated in effects because writing a ref during render is a React rule
  // violation (and genuinely unsafe under concurrent rendering).
  const snapIndexRef = useRef(snapIndex)
  const snapsRef = useRef(snaps)
  useEffect(() => { snapIndexRef.current = snapIndex })
  useEffect(() => { snapsRef.current = snaps })

  useEffect(() => {
    const s = {
      pointerId: -1, startY: 0, lastY: 0, lastT: 0, velocity: 0,
      active: false, target: null as HTMLElement | null,
    }

    function onTouchMove(e: TouchEvent) {
      // Once dragging, stop the browser scrolling the page out from under us.
      if (s.active && e.cancelable) e.preventDefault()
    }

    function onPointerMove(e: PointerEvent) {
      if (e.pointerId !== s.pointerId) return
      const dy = e.clientY - s.startY

      if (!s.active) {
        if (Math.abs(dy) < DRAG_THRESHOLD) return
        s.active = true
      }
      const now = e.timeStamp
      if (now > s.lastT) s.velocity = (e.clientY - s.lastY) / (now - s.lastT)
      s.lastY = e.clientY
      s.lastT = now

      // Upward drag past the tallest snap resists, so the sheet can't be hauled
      // off the top of the screen.
      setDragY(dy < 0 ? dy / 3 : dy)
    }

    function onPointerUp(e: PointerEvent) {
      if (e.pointerId !== s.pointerId) return
      const dy = e.clientY - s.startY
      // Read the gesture state *before* cleaning up: `cleanup` resets `active`,
      // so testing it afterwards makes every drag look like a tap.
      const dragged = s.active
      const velocity = s.velocity
      cleanup()

      if (!dragged) return                      // a tap, not a drag

      const outcome = resolveDrag(dy, velocity, snapIndexRef.current, snapsRef.current.length)
      if (outcome.kind === 'dismiss') { setDragY(null); onCloseRef.current(); return }
      if (outcome.kind === 'snap') setSnapIndex(outcome.index)
      setDragY(null)
    }

    // A cancelled pointer is the system taking the gesture away (a scroll takes
    // over, the app backgrounds). Snap back rather than resolving it — acting on
    // a drag the user didn't finish is how a sheet dismisses itself for no
    // visible reason.
    function onPointerCancel(e: PointerEvent) {
      if (e.pointerId !== s.pointerId) return
      cleanup()
      setDragY(null)
    }

    function cleanup() {
      document.removeEventListener('pointermove', onPointerMove)
      document.removeEventListener('pointerup', onPointerUp)
      document.removeEventListener('pointercancel', onPointerCancel)
      document.removeEventListener('touchmove', onTouchMove)
      if (s.target?.hasPointerCapture(s.pointerId)) s.target.releasePointerCapture(s.pointerId)
      s.target = null
      s.pointerId = -1
      s.active = false
    }

    api.current.onPointerDown = (e: React.PointerEvent) => {
      // Selects, inputs and buttons inside the sheet must keep working; the
      // handle is the drag surface, everything marked opt-out is not.
      if ((e.target as HTMLElement).closest('[data-no-drag]')) return

      // Capture the pointer on the handle. Without it a drag over the sheet's
      // own text starts a native selection/drag in the browser, which swallows
      // the rest of the gesture — pointermove stops arriving and pointerup never
      // fires, so the sheet sticks mid-drag. Capture also guarantees delivery
      // when the finger leaves the handle, which every drag does immediately.
      // Captured events still bubble to the document listeners below.
      const target = e.currentTarget as HTMLElement
      target.setPointerCapture(e.pointerId)
      e.preventDefault()
      s.target = target
      s.pointerId = e.pointerId
      s.startY = s.lastY = e.clientY
      s.lastT = e.timeStamp
      s.velocity = 0
      s.active = false
      document.addEventListener('pointermove', onPointerMove)
      document.addEventListener('pointerup', onPointerUp)
      document.addEventListener('pointercancel', onPointerCancel)
      document.addEventListener('touchmove', onTouchMove, { passive: false })
    }

    return cleanup
    // Mount-once by design — everything variable is read through a ref.
  }, [])

  const onPointerDown = useCallback((e: React.PointerEvent) => api.current.onPointerDown(e), [])

  const height = `${Math.round(snaps[snapIndex] * 100)}dvh`
  // While dragging, follow the finger with no transition; on release, animate.
  const transform = open
    ? `translateY(${dragY ?? 0}px)`
    : 'translateY(100%)'

  return (
    <>
      <div
        onClick={() => onCloseRef.current()}
        aria-hidden="true"
        style={{
          position: 'fixed', inset: 0, zIndex,
          background: 'rgba(17,20,24,0.55)', backdropFilter: 'blur(2px)',
          opacity: open ? 1 : 0, pointerEvents: open ? 'auto' : 'none',
          transition: 'opacity 180ms var(--ease-out)',
        }}
      />
      <div
        ref={sheetRef}
        role="dialog"
        aria-modal="true"
        aria-label={title ? undefined : label}
        aria-labelledby={title ? titleId : undefined}
        style={{
          position: 'fixed', left: 0, right: 0, bottom: 0, zIndex: zIndex + 1,
          height, maxHeight: '94dvh',
          display: 'flex', flexDirection: 'column',
          background: 'var(--color-paper)',
          borderTop: '1px solid var(--color-ink-200)',
          borderTopLeftRadius: 16, borderTopRightRadius: 16,
          // The design system's --shadow-drawer has a -4px *X* offset, authored
          // for a right-side drawer; a bottom sheet needs the lift above it.
          boxShadow: '0 -8px 40px rgba(0,0,0,0.45)',
          paddingBottom: 'env(safe-area-inset-bottom)',
          transform,
          transition: dragY === null
            // `visibility` is transitioned rather than toggled so the slide-out
            // is actually visible: hiding immediately would cut it off at frame
            // one. Opening flips it at 0s; closing waits out the transform.
            ? `transform 220ms var(--ease-out), height 220ms var(--ease-out), visibility 0s linear ${open ? '0s' : '220ms'}`
            : 'none',
          touchAction: 'none',
          visibility: open ? 'visible' : 'hidden',
        }}
      >
        {/* Grab handle — a real target, not decoration. 24px of vertical hit
            area around a 4px bar, which is the smallest that doesn't feel fussy. */}
        <div
          onPointerDown={onPointerDown}
          aria-hidden="true"
          style={{
            display: 'flex', justifyContent: 'center', alignItems: 'center',
            padding: '10px 0 6px', flexShrink: 0, cursor: 'grab', touchAction: 'none',
            userSelect: 'none',
          }}
        >
          <div style={{ width: 40, height: 4, borderRadius: 2, background: 'var(--color-ink-300)' }} />
        </div>

        {title && (
          <div
            onPointerDown={onPointerDown}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '0 16px 10px', flexShrink: 0, cursor: 'grab', touchAction: 'none',
              userSelect: 'none',
            }}
          >
            <div id={titleId} style={{
              fontFamily: 'var(--font-display)', fontSize: 15, fontWeight: 600,
              color: 'var(--color-ink-900)',
            }}>
              {title}
            </div>
            {/* The drag gesture is an addition, not a replacement: backdrop-tap,
                Escape and this button all still close. `data-no-drag` is what
                keeps it tappable — without it a press here starts a drag and the
                click never lands. */}
            <button
              data-no-drag
              onClick={onClose}
              aria-label="Close"
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                width: 44, height: 44, marginRight: -10, flexShrink: 0,
                border: 'none', background: 'transparent', cursor: 'pointer',
                color: 'var(--color-ink-500)',
              }}
            >
              <X size={18} strokeWidth={1.5} />
            </button>
          </div>
        )}

        <div style={{ overflowY: 'auto', flex: 1, padding: '0 16px 16px', touchAction: 'pan-y' }}>
          {children}
        </div>
      </div>
    </>
  )
}
