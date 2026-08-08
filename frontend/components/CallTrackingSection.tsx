'use client'
import { useCallback, useEffect, useState } from 'react'
import { Phone, Search, CheckCircle2, MessageSquare, Zap } from 'lucide-react'
import {
  getCallSettings, updateCallSettings, searchCallNumbers, purchaseCallNumber,
  releaseCallNumber, activateCallTracking,
} from '@/lib/api'
import { ConfirmModal } from '@/components/ConfirmModal'
import type { CallSettings, AvailableNumber } from '@/lib/types'

/**
 * Settings card for call tracking.
 *
 * The headline path is one click: type the phone your business line already
 * rings on, accept, and the server picks a number in that line's area code,
 * points it at you, and switches on the missed-call auto-text. Owners who care
 * which digits they get can open "Pick the number myself" for the old
 * search-and-buy flow — both end at the same tracking number.
 *
 * Once a number exists, texting is two-way with no extra setup: replies to it
 * land on the caller's record, and texts you send from a record go out from it.
 */
export function CallTrackingSection() {
  const [settings, setSettings] = useState<CallSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Setup state
  const [forwardTo, setForwardTo] = useState('')
  const [autoReply, setAutoReply] = useState(true)
  const [activating, setActivating] = useState(false)
  const [pickOwn, setPickOwn] = useState(false)
  const [areaCode, setAreaCode] = useState('')
  const [results, setResults] = useState<AvailableNumber[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [buying, setBuying] = useState<string | null>(null)

  // Configured state
  const [editForward, setEditForward] = useState('')
  const [saving, setSaving] = useState(false)
  const [savingReply, setSavingReply] = useState(false)
  const [editReply, setEditReply] = useState('')
  const [confirmRelease, setConfirmRelease] = useState(false)
  const [releasing, setReleasing] = useState(false)

  const load = useCallback(async () => {
    try {
      const s = await getCallSettings()
      setSettings(s)
      setEditForward(s.number?.forward_to ?? '')
      setEditReply(s.auto_reply?.body ?? '')
    } catch {
      // Transient failures: leave the card in its muted state.
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const forwardDigits = forwardTo.replace(/\D/g, '').length

  async function handleActivate() {
    if (forwardDigits < 10) {
      setError('Enter your business phone (10 digits) first — that’s where calls forward to.')
      return
    }
    setActivating(true)
    setError(null)
    try {
      await activateCallTracking({ forward_to: forwardTo, auto_reply: autoReply })
      await load()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not set up call tracking')
    } finally {
      setActivating(false)
    }
  }

  async function handleSearch() {
    setSearching(true)
    setError(null)
    try {
      // Default the search to the business line's own area code, so the
      // manual path starts where the one-click path would have landed.
      const code = areaCode || forwardTo.replace(/\D/g, '').slice(-10, -7)
      const { numbers } = await searchCallNumbers(code ? { area_code: code } : {})
      setResults(numbers)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Number search failed')
    } finally {
      setSearching(false)
    }
  }

  async function handleBuy(phoneNumber: string) {
    if (forwardDigits < 10) {
      setError('Enter your business phone (10 digits) first — that’s where calls forward to.')
      return
    }
    setBuying(phoneNumber)
    setError(null)
    try {
      await purchaseCallNumber(phoneNumber, forwardTo)
      // Buying a specific number skips activation, so honour the auto-text
      // choice here too rather than silently dropping it.
      if (autoReply) await updateCallSettings({ auto_reply: true })
      setResults(null)
      await load()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Purchase failed')
    } finally {
      setBuying(null)
    }
  }

  async function handleSaveForward() {
    setSaving(true)
    setError(null)
    try {
      await updateCallSettings({ forward_to: editForward })
      await load()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not save')
    } finally {
      setSaving(false)
    }
  }

  async function handleToggleReply(enabled: boolean) {
    setSavingReply(true)
    setError(null)
    try {
      await updateCallSettings({ auto_reply: enabled })
      await load()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not change the auto-text')
    } finally {
      setSavingReply(false)
    }
  }

  async function handleSaveReplyBody() {
    setSavingReply(true)
    setError(null)
    try {
      await updateCallSettings({ auto_reply_body: editReply })
      await load()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not save the auto-text')
    } finally {
      setSavingReply(false)
    }
  }

  async function handleRelease() {
    if (!settings?.number) return
    setReleasing(true)
    setError(null)
    try {
      await releaseCallNumber(settings.number.id)
      setConfirmRelease(false)
      await load()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not release the number')
    } finally {
      setReleasing(false)
    }
  }

  const inputStyle = {
    padding: '8px 10px', fontSize: 13, borderRadius: 'var(--radius-button)',
    border: '1px solid var(--color-ink-200)', background: 'var(--color-paper)',
    color: 'var(--color-ink-900)',
  } as const

  const linkButtonStyle = {
    padding: 0, border: 'none', background: 'none', cursor: 'pointer',
    fontSize: 12, color: 'var(--color-link)', textDecoration: 'underline',
  } as const

  return (
    <section>
      <h2 className="t-eyebrow" style={{ marginBottom: 6 }}>Call tracking</h2>
      <p style={{ fontSize: 13, color: 'var(--color-ink-400)', margin: '0 0 12px' }}>
        A dedicated local number that forwards to your real phone. Every inbound call is
        logged on the caller&apos;s record, unknown callers become new leads automatically,
        missed calls drop an urgent call-back task on your plate, and texts to the number
        thread onto the same record.
      </p>

      <div style={{
        padding: '14px 16px', background: 'var(--color-surface)',
        border: '1px solid var(--color-ink-200)', borderRadius: 'var(--radius-card)',
      }}>
        {loading ? (
          <span style={{ fontSize: 13, color: 'var(--color-ink-400)' }}>Loading…</span>
        ) : !settings?.configured ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Phone size={18} strokeWidth={1.5} style={{ color: 'var(--color-ink-500)', flexShrink: 0 }} />
            <span style={{ fontSize: 13, color: 'var(--color-ink-400)' }}>
              Call tracking isn&apos;t enabled on this server.
            </span>
          </div>
        ) : settings.number ? (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, fontWeight: 600, color: 'var(--color-moss)', marginBottom: 10 }}>
              <CheckCircle2 size={14} strokeWidth={2} />
              Tracking number active: {settings.number.friendly_name || settings.number.phone_number}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <label style={{ fontSize: 12, color: 'var(--color-ink-500)' }}>Forward calls to</label>
              <input
                value={editForward}
                onChange={e => setEditForward(e.target.value)}
                placeholder="(713) 555-0142"
                style={{ ...inputStyle, width: 160 }}
              />
              <button
                onClick={handleSaveForward}
                disabled={saving || !editForward.trim() || editForward === (settings.number.forward_to ?? '')}
                className="btn-primary"
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
              <button
                onClick={() => setConfirmRelease(true)}
                style={{
                  marginLeft: 'auto', padding: '8px 12px', fontSize: 13,
                  borderRadius: 'var(--radius-button)', border: '1px solid var(--color-ink-200)',
                  background: 'transparent', color: 'var(--color-danger)', cursor: 'pointer',
                }}
              >
                Release number
              </button>
            </div>
            {!settings.number.forward_to && (
              <p style={{ fontSize: 12, color: 'var(--color-warning, #B45309)', margin: '8px 0 0' }}>
                No forwarding phone set — calls to your tracking number can&apos;t connect until you add one.
              </p>
            )}

            {/* Missed-call auto-text */}
            <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--color-ink-100, rgba(0,0,0,0.06))' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--color-ink-900)', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={settings.auto_reply?.enabled ?? false}
                  disabled={savingReply}
                  onChange={e => handleToggleReply(e.target.checked)}
                />
                <MessageSquare size={13} strokeWidth={1.5} style={{ color: 'var(--color-accent)' }} />
                Text missed callers back automatically
              </label>
              {settings.auto_reply?.enabled && (
                <div style={{ marginTop: 8 }}>
                  <textarea
                    value={editReply}
                    onChange={e => setEditReply(e.target.value)}
                    rows={2}
                    maxLength={480}
                    style={{ ...inputStyle, width: '100%', fontFamily: 'var(--font-sans)', resize: 'vertical' }}
                  />
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 6 }}>
                    <button
                      onClick={handleSaveReplyBody}
                      disabled={savingReply || !editReply.trim() || editReply === (settings.auto_reply.body ?? '')}
                      className="btn-primary"
                    >
                      {savingReply ? 'Saving…' : 'Save text'}
                    </button>
                    <span style={{ fontSize: 11, color: 'var(--color-ink-400)' }}>
                      Sent from your tracking number, so their reply threads onto the lead.
                      Use <code>{'{{business_name}}'}</code> to insert your business name.
                    </span>
                  </div>
                </div>
              )}
            </div>

            <p style={{ fontSize: 12, color: 'var(--color-ink-400)', margin: '12px 0 0' }}>
              Want more than the one auto-text? Build multi-step follow-ups in <a href="/settings?tab=automation" style={{ color: 'var(--color-link)' }}>Settings → Automation</a>.
            </p>
          </div>
        ) : (
          <div>
            {/* One-click activation: business line in, working number out. */}
            <label style={{ display: 'block', fontSize: 12, color: 'var(--color-ink-500)', marginBottom: 6 }}>
              What phone should calls ring on?
            </label>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <input
                value={forwardTo}
                onChange={e => setForwardTo(e.target.value)}
                placeholder="Your business line, e.g. (713) 555-0142"
                style={{ ...inputStyle, width: 250 }}
              />
              <button
                onClick={handleActivate}
                disabled={activating || forwardDigits < 10}
                className="btn-primary"
                style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
              >
                <Zap size={13} strokeWidth={2} />
                {activating ? 'Setting up…' : 'Turn on call tracking'}
              </button>
            </div>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--color-ink-600)', margin: '10px 0 0', cursor: 'pointer' }}>
              <input type="checkbox" checked={autoReply} onChange={e => setAutoReply(e.target.checked)} />
              Text missed callers back automatically
            </label>
            <p style={{ fontSize: 12, color: 'var(--color-ink-400)', margin: '8px 0 0' }}>
              We&apos;ll get you a number in your own area code and point it at that phone.
              Your calls still ring where they always have.
            </p>

            {/* Escape hatch for owners who want specific digits. */}
            <div style={{ marginTop: 12 }}>
              <button onClick={() => setPickOwn(v => !v)} style={linkButtonStyle}>
                {pickOwn ? 'Never mind — just pick one for me' : 'Pick the number myself'}
              </button>
            </div>

            {pickOwn && (
              <div style={{ marginTop: 10 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <input
                    value={areaCode}
                    onChange={e => setAreaCode(e.target.value.replace(/\D/g, '').slice(0, 3))}
                    placeholder="Area code"
                    style={{ ...inputStyle, width: 90 }}
                  />
                  <button onClick={handleSearch} disabled={searching} className="btn-primary" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                    <Search size={13} strokeWidth={2} />
                    {searching ? 'Searching…' : 'Find numbers'}
                  </button>
                </div>
                {results && (
                  results.length === 0 ? (
                    <p style={{ fontSize: 13, color: 'var(--color-ink-400)', margin: '10px 0 0' }}>
                      No numbers found — try another area code.
                    </p>
                  ) : (
                    <ul style={{ listStyle: 'none', margin: '12px 0 0', padding: 0, display: 'grid', gap: 6 }}>
                      {results.map(n => (
                        <li key={n.phone_number} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13 }}>
                          <Phone size={13} strokeWidth={1.5} style={{ color: 'var(--color-ink-400)', flexShrink: 0 }} />
                          <span style={{ fontWeight: 600, color: 'var(--color-ink-900)' }}>{n.friendly_name}</span>
                          <span style={{ color: 'var(--color-ink-400)' }}>
                            {[n.locality, n.region].filter(Boolean).join(', ')}
                          </span>
                          <button
                            onClick={() => handleBuy(n.phone_number)}
                            disabled={buying !== null}
                            className="btn-primary"
                            style={{ marginLeft: 'auto' }}
                          >
                            {buying === n.phone_number ? 'Buying…' : 'Buy'}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {error && <p style={{ fontSize: 12, color: 'var(--color-rose)', marginTop: 8 }}>{error}</p>}

      {confirmRelease && settings?.number && (
        <ConfirmModal
          title="Release tracking number?"
          message={`${settings.number.friendly_name || settings.number.phone_number} will stop receiving calls immediately and can't be recovered. Anywhere you've published it goes dead.`}
          confirmLabel="Release number"
          danger
          loading={releasing}
          onConfirm={handleRelease}
          onCancel={() => setConfirmRelease(false)}
        />
      )}
    </section>
  )
}
