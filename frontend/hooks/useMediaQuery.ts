import { useCallback, useSyncExternalStore } from 'react'

/**
 * Breakpoint below which the UI switches to its touch/one-handed layout.
 *
 * Named rather than inlined because the map's chrome, its bottom sheet and its
 * pickers all have to agree on the same threshold; three components each
 * deciding "767" independently is how they drift apart.
 *
 * Note the rest of the app is CSS-responsive — this hook exists for the cases
 * where the *behaviour* differs, not just the styling (a dropdown that becomes a
 * bottom sheet, a control that moves out of the thumb path), which CSS can't
 * express.
 */
export const MOBILE_BREAKPOINT = '(max-width: 767px)'

/**
 * Track a media query on the client.
 *
 * The SSR snapshot is deliberately `false`, making the desktop layout the
 * hydration baseline: the server has no viewport, so it must render *something*,
 * and both possible answers are wrong half the time. Returning a stable `false`
 * at least makes server and first client render agree, which is what keeps React
 * from throwing a hydration mismatch. The correct value lands on the first
 * post-hydration commit.
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback((onChange: () => void) => {
    const mq = window.matchMedia(query)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [query])
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
    () => false,
  )
}

/** Convenience wrapper for the app's one breakpoint. */
export function useIsMobile(): boolean {
  return useMediaQuery(MOBILE_BREAKPOINT)
}
