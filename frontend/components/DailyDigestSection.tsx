'use client'
import { useEffect, useState } from 'react'
import { Coffee } from 'lucide-react'
import { getPreferences, updatePreferences } from '@/lib/api'

/**
 * Opt-in toggle for the morning "who to call today" email (api/digest.py).
 * The habit trigger has to live outside the app — this is where it's switched on.
 */
export function DailyDigestSection() {
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    getPreferences()
      .then(p => setEnabled(!!p.daily_digest))
      .catch(() => setEnabled(false))
  }, [])

  async function toggle() {
    if (enabled == null || saving) return
    const next = !enabled
    setSaving(true)
    setEnabled(next)
    try {
      await updatePreferences({ daily_digest: next })
    } catch {
      setEnabled(!next)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <Coffee size={14} strokeWidth={1.5} style={{ color: 'var(--color-accent)' }} />
        <h2 className="t-eyebrow" style={{ margin: 0 }}>Morning call list</h2>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
        <p style={{ margin: 0, fontSize: 13, color: 'var(--color-ink-500)', maxWidth: 480 }}>
          One short email every morning: the leads to call today, quotes to chase,
          and anything overdue. No noise — it skips days with nothing to do.
        </p>
        <button
          onClick={toggle}
          disabled={enabled == null || saving}
          role="switch"
          aria-checked={!!enabled}
          aria-label="Daily who-to-call email"
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
