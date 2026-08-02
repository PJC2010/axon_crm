// Analytics event helpers — Google Analytics 4 and the Meta (Facebook) pixel.
//
// The tags themselves are mounted in app/layout.tsx, gated on
// NEXT_PUBLIC_GA_MEASUREMENT_ID and NEXT_PUBLIC_META_PIXEL_ID respectively.
// Every helper here no-ops when its var is unset (or during SSR), so call
// sites never need to check whether analytics is configured — same
// degrade-gracefully convention as the backend pipeline. The conversion
// helpers below fan out to both destinations; call sites stay unaware.
//
// Page views are automatic (gtag tracks history changes); this module is only
// for the handful of conversion events worth measuring explicitly. Event names
// follow the GA4 recommended-events vocabulary so they light up standard
// reports without extra configuration:
// https://developers.google.com/analytics/devguides/collection/ga4/reference/events
import { sendGAEvent } from '@next/third-parties/google'

const GA_ID = process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID
const PIXEL_ID = process.env.NEXT_PUBLIC_META_PIXEL_ID

export type AuthMethod = 'email' | 'google' | 'apple'

/** Fire a GA4 event. Safe to call unconditionally — no-op without GA. */
export function trackEvent(name: string, params?: Record<string, unknown>) {
  if (!GA_ID || typeof window === 'undefined') return
  sendGAEvent('event', name, params ?? {})
}

// The fbq handle the Meta base snippet installs on window. Undefined until
// that snippet runs (components/MetaPixel), which callers treat as "off".
// Same untyped-third-party-global pattern the OAuth SDKs use in app/login.
function fbq(): ((...args: unknown[]) => void) | undefined {
  if (!PIXEL_ID || typeof window === 'undefined') return undefined
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (window as any).fbq
}

/**
 * Fire a Meta *standard* event (one of the names Meta recognises for ad
 * optimisation and reporting). Use trackMetaCustom for anything else — an
 * unrecognised name here would sit unusable in the standard-event reports.
 */
export function trackMeta(name: string, params?: Record<string, unknown>) {
  fbq()?.('track', name, params ?? {})
}

/** Fire a Meta custom event (no standard-event equivalent exists). */
export function trackMetaCustom(name: string, params?: Record<string, unknown>) {
  fbq()?.('trackCustom', name, params ?? {})
}

/**
 * Manual PageView for a client-side route change. GA tracks history changes
 * on its own; fbq does not, so components/MetaPixel drives this on navigation.
 */
export function trackMetaPageView() {
  trackMeta('PageView')
}

/** New workspace created (self-serve signup). */
export function trackSignUp(method: AuthMethod) {
  trackEvent('sign_up', { method })
  trackMeta('CompleteRegistration', { method })
}

/** Successful login. */
export function trackLogin(method: AuthMethod) {
  trackEvent('login', { method })
  // Meta has no standard event for a returning-user login — it is retention,
  // not conversion, so it stays out of the standard-event reports.
  trackMetaCustom('Login', { method })
}

/** User clicked through to Stripe Checkout for a paid plan. */
export function trackBeginCheckout(plan: string) {
  trackEvent('begin_checkout', { item_name: plan })
  trackMeta('InitiateCheckout', { content_name: plan })
}
