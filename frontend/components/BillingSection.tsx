'use client'
import { SkeletonPanel } from './ds'
import { useCallback, useEffect, useState } from 'react'
import { BadgeCheck, Check, ExternalLink } from 'lucide-react'
import { getBilling, startPlanCheckout, openBillingPortal } from '@/lib/api'
import { trackBeginCheckout } from '@/lib/analytics'
import type { BillingInfo } from '@/lib/types'

const PLAN_ORDER = ['starter', 'growth', 'pro']

function fmtDate(iso?: string | null): string | null {
  if (!iso) return null
  const d = new Date(iso)
  return isNaN(d.getTime())
    ? null
    : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

/** Settings card for the account's own Axon subscription: current plan + trial
 *  state, plan cards with Checkout upgrade buttons, and the Stripe customer
 *  portal for card/cancel/plan changes. Returning from Stripe lands back on
 *  /settings (?billing=success|cancelled); the billing webhook is what actually
 *  flips the plan, so we just re-fetch. */
export function BillingSection() {
  const [info, setInfo] = useState<BillingInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [busyPlan, setBusyPlan] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setInfo(await getBilling())
    } catch {
      // Transient failure: leave the card muted rather than blank the page.
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  async function handleCheckout(plan: string) {
    setBusyPlan(plan)
    setError(null)
    try {
      const { url } = await startPlanCheckout(plan)
      trackBeginCheckout(plan)
      window.location.href = url
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not start checkout')
      setBusyPlan(null)
    }
  }

  async function handlePortal() {
    setBusyPlan('__portal__')
    setError(null)
    try {
      const { url } = await openBillingPortal()
      window.location.href = url
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not open the billing portal')
      setBusyPlan(null)
    }
  }

  const trialEnds = fmtDate(info?.trial_ends_at)
  const periodEnd = fmtDate(info?.current_period_end)
  const statusLine = !info ? null
    : info.status === 'trialing' && trialEnds ? `Free trial — full access until ${trialEnds}.`
    : info.status === 'trial_expired' ? 'Your trial has ended — pick a plan to turn the optional modules back on.'
    : info.status === 'past_due' ? 'Your last payment failed — update your card in the billing portal.'
    : info.cancel_at_period_end && periodEnd ? `Cancels at the end of the period (${periodEnd}).`
    : info.has_subscription && periodEnd ? `Renews ${periodEnd}.`
    : null

  const plans = info
    ? [...info.plans].sort((a, b) => PLAN_ORDER.indexOf(a.plan) - PLAN_ORDER.indexOf(b.plan))
    : []

  return (
    <section>
      <h2 className="t-eyebrow" style={{ marginBottom: 6 }}>Plan &amp; billing</h2>
      <p style={{ fontSize: 13, color: 'var(--color-ink-400)', margin: '0 0 12px' }}>
        Flat monthly pricing, no contract — change or cancel anytime. Plan changes made in
        Stripe take effect here within a few seconds.
      </p>

      {loading ? (
        <SkeletonPanel lines={2} />
      ) : !info ? (
        <p style={{ fontSize: 13, color: 'var(--color-ink-400)' }}>Billing info unavailable.</p>
      ) : (
        <>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', marginBottom: 12,
            background: 'var(--color-surface)', border: '1px solid var(--color-ink-200)',
            borderRadius: 'var(--radius-card)', flexWrap: 'wrap',
          }}>
            <BadgeCheck size={16} strokeWidth={1.5} style={{ color: 'var(--color-accent)', flexShrink: 0 }} />
            <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-ink-900)', textTransform: 'capitalize' }}>
              {info.plan_name} plan
            </span>
            {statusLine && (
              <span style={{ fontSize: 12.5, color: 'var(--color-ink-500)' }}>{statusLine}</span>
            )}
            {info.has_subscription && (
              <button
                onClick={handlePortal}
                disabled={busyPlan !== null}
                className="dash-icon-btn"
                style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 5, fontSize: 12 }}
              >
                <ExternalLink size={12} strokeWidth={1.5} />
                {busyPlan === '__portal__' ? 'Opening…' : 'Manage billing'}
              </button>
            )}
          </div>

          {!info.configured ? (
            <p style={{ fontSize: 12.5, color: 'var(--color-ink-400)' }}>
              Self-serve upgrades aren&apos;t enabled on this server — plans are managed by the
              Axon team. Email us to change plans.
            </p>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 10 }}>
              {plans.map((p) => {
                const isCurrent = p.plan === info.plan_name && info.has_subscription
                return (
                  <div key={p.plan} style={{
                    padding: '14px 16px', background: 'var(--color-surface)',
                    border: `1px solid ${isCurrent ? 'var(--color-accent)' : 'var(--color-ink-200)'}`,
                    borderRadius: 'var(--radius-card)', display: 'flex', flexDirection: 'column', gap: 6,
                  }}>
                    <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-ink-900)' }}>{p.label}</span>
                      <span style={{ fontSize: 13, color: 'var(--color-ink-700)' }}>
                        <b>${p.monthly_usd}</b><span style={{ fontSize: 11, color: 'var(--color-ink-400)' }}>/mo</span>
                      </span>
                    </div>
                    <p style={{ fontSize: 12, color: 'var(--color-ink-500)', margin: 0, lineHeight: 1.45, flex: 1 }}>
                      {p.blurb}
                    </p>
                    {isCurrent ? (
                      <span style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, fontWeight: 600, color: 'var(--color-moss)' }}>
                        <Check size={13} strokeWidth={2} /> Current plan
                      </span>
                    ) : (
                      <button
                        onClick={() => handleCheckout(p.plan)}
                        disabled={busyPlan !== null || !p.purchasable}
                        className="btn-primary"
                        style={{ alignSelf: 'flex-start' }}
                        title={p.purchasable ? undefined : 'Not available for self-serve checkout yet'}
                      >
                        {busyPlan === p.plan ? 'Opening…' : info.has_subscription ? 'Switch plan' : 'Choose plan'}
                      </button>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </>
      )}

      {error && <p style={{ fontSize: 12, color: 'var(--color-rose)', marginTop: 8 }}>{error}</p>}
    </section>
  )
}
