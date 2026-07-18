// Google Analytics 4 event helpers.
//
// The <GoogleAnalytics> tag itself is mounted in app/layout.tsx, gated on
// NEXT_PUBLIC_GA_MEASUREMENT_ID. Every helper here no-ops when that var is
// unset (or during SSR), so call sites never need to check whether analytics
// is configured — same degrade-gracefully convention as the backend pipeline.
//
// Page views are automatic (gtag tracks history changes); this module is only
// for the handful of conversion events worth measuring explicitly. Event names
// follow the GA4 recommended-events vocabulary so they light up standard
// reports without extra configuration:
// https://developers.google.com/analytics/devguides/collection/ga4/reference/events
import { sendGAEvent } from '@next/third-parties/google'

const GA_ID = process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID

export type AuthMethod = 'email' | 'google' | 'apple'

/** Fire a GA4 event. Safe to call unconditionally — no-op without GA. */
export function trackEvent(name: string, params?: Record<string, unknown>) {
  if (!GA_ID || typeof window === 'undefined') return
  sendGAEvent('event', name, params ?? {})
}

/** New workspace created (self-serve signup). */
export function trackSignUp(method: AuthMethod) {
  trackEvent('sign_up', { method })
}

/** Successful login. */
export function trackLogin(method: AuthMethod) {
  trackEvent('login', { method })
}

/** User clicked through to Stripe Checkout for a paid plan. */
export function trackBeginCheckout(plan: string) {
  trackEvent('begin_checkout', { item_name: plan })
}
