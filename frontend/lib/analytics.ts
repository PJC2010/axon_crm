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
 * A shared id for one logical conversion, so the browser Pixel and the
 * server-side Conversions API (api/connectors/meta_capi.py) report the same
 * event once instead of twice — Meta dedups on `eventID` + event name. Pass the
 * same value to both sides. randomUUID with a cheap fallback for old browsers.
 */
export function newEventId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return `e-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

/**
 * Fire a Meta *standard* event (one of the names Meta recognises for ad
 * optimisation and reporting). Use trackMetaCustom for anything else — an
 * unrecognised name here would sit unusable in the standard-event reports.
 * Pass `eventID` when a server-side counterpart fires the same conversion.
 */
export function trackMeta(name: string, params?: Record<string, unknown>, eventID?: string) {
  fbq()?.('track', name, params ?? {}, eventID ? { eventID } : undefined)
}

/** Fire a Meta custom event (no standard-event equivalent exists). */
export function trackMetaCustom(name: string, params?: Record<string, unknown>, eventID?: string) {
  fbq()?.('trackCustom', name, params ?? {}, eventID ? { eventID } : undefined)
}

/**
 * Manual PageView for a client-side route change. GA tracks history changes
 * on its own; fbq does not, so components/MetaPixel drives this on navigation.
 */
export function trackMetaPageView() {
  trackMeta('PageView')
}

/** New workspace created (self-serve signup). Axon's trial needs no card, so a
 *  signup *is* a trial start — fire both the registration and StartTrial
 *  standard events, the latter being the funnel event the ad strategy
 *  optimises toward before the paid Subscribe.
 *
 *  `eventID` (from newEventId, passed through the signup request) is set on the
 *  StartTrial only: the signup route fires the same StartTrial server-side with
 *  hashed match keys, and a shared eventID lets Meta dedup the pair into one.
 *  CompleteRegistration has no server twin, so it stays un-ided. */
export function trackSignUp(method: AuthMethod, eventID?: string) {
  trackEvent('sign_up', { method })
  trackMeta('CompleteRegistration', { method })
  trackMeta('StartTrial', { method, value: 0, currency: 'USD' }, eventID)
}

/** Read the Meta pixel's first-party cookies so the signup request can forward
 *  them to the (cross-origin) API, where they lift the server StartTrial's EMQ.
 *  _fbp is set by the base pixel; _fbc only exists after an ad click (fbclid).
 *  Returns undefined values when absent or off the browser. */
export function readFbCookies(): { fbp?: string; fbc?: string } {
  if (typeof document === 'undefined') return {}
  const read = (name: string) =>
    document.cookie.split('; ').find((c) => c.startsWith(`${name}=`))?.split('=')[1]
  return { fbp: read('_fbp'), fbc: read('_fbc') }
}

/** Visitor used the public ZIP-demo widget and got scored leads back — the
 *  "value delivered before the ask" moment the ad strategy optimises on.
 *  Fires on a successful sample; see components/ZipSampleWidget. */
export function trackZipDemo(zip: string, trade?: string) {
  trackEvent('view_search_results', { search_term: zip, trade })
  trackMeta('ViewContent', { content_name: 'zip_demo', content_category: trade || 'any', zip })
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
