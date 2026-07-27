'use client'
import { useEffect, useState } from 'react'
import { MessageSquare } from 'lucide-react'
import { getMe, updateSmsConsent } from '@/lib/api'

/**
 * Opt-in/out toggle for SMS from Axon (account + Storm Mode territory alerts).
 * Consent is recorded server-side with timestamps (users.sms_consent,
 * migration 064) — this is the in-app opt-out path the privacy policy and the
 * A2P 10DLC campaign application both promise.
 */
export function SmsAlertsSection() {
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    getMe()
      .then(u => setEnabled(!!u.sms_consent))
      .catch(() => setEnabled(false))
  }, [])

  async function toggle() {
    if (enabled == null || saving) return
    const next = !enabled
    setSaving(true)
    setEnabled(next)
    try {
      await updateSmsConsent(next)
    } catch {
      setEnabled(!next)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <MessageSquare size={14} strokeWidth={1.5} style={{ color: 'var(--color-accent)' }} />
        <h2 className="t-eyebrow" style={{ margin: 0 }}>Text message alerts</h2>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
        <p style={{ margin: 0, fontSize: 13, color: 'var(--color-ink-500)', maxWidth: 480 }}>
          SMS from Axon about your account, scoring results, and territory alerts
          (Storm Mode). Msg frequency varies. Msg &amp; data rates may apply.
          Reply STOP to any message to opt out, or switch this off anytime.
        </p>
        <button
          onClick={toggle}
          disabled={enabled == null || saving}
          role="switch"
          aria-checked={!!enabled}
          aria-label="Text message alerts from Axon"
          style={{
            width: 44, height: 24, borderRadius: 12, border: 'none',
            cursor: enabled == null || saving ? 'not-allowed' : 'pointer',
            background: enabled ? 'var(--color-moss)' : 'var(--color-ink-300)',
            position: 'relative', transition: 'background 0.2s', flexShrink: 0,
          }}
        >
          <span style={{
            position: 'absolute', top: 3, left: enabled ? 23 : 3,
            width: 18, height: 18, borderRadius: '50%', background: '#fff',
            transition: 'left 0.2s',
          }} />
        </button>
      </div>
    </section>
  )
}
