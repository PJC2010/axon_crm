'use client'
import { useCallback, useEffect, useState } from 'react'
import { Phone, Search, CheckCircle2 } from 'lucide-react'
import {
  getCallSettings, updateCallSettings, searchCallNumbers, purchaseCallNumber, releaseCallNumber,
} from '@/lib/api'
import { ConfirmModal } from '@/components/ConfirmModal'
import type { CallSettings, AvailableNumber } from '@/lib/types'

/** Settings card for call tracking: buy a local tracking number that forwards
 *  to the business's real phone, edit the forwarding destination, or release
 *  the number. Every inbound call is logged and unknown callers become leads. */
export function CallTrackingSection() {
  const [settings, setSettings] = useState<CallSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Setup state
  const [areaCode, setAreaCode] = useState('')
  const [forwardTo, setForwardTo] = useState('')
  const [results, setResults] = useState<AvailableNumber[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [buying, setBuying] = useState<string | null>(null)

  // Configured state
  const [editForward, setEditForward] = useState('')
  const [saving, setSaving] = useState(false)
  const [confirmRelease, setConfirmRelease] = useState(false)
  const [releasing, setReleasing] = useState(false)

  const load = useCallback(async () => {
    try {
      const s = await getCallSettings()
      setSettings(s)
      setEditForward(s.number?.forward_to ?? '')
    } catch {
      // Transient failures: leave the card in its muted state.
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  async function handleSearch() {
    setSearching(true)
    setError(null)
    try {
      const { numbers } = await searchCallNumbers(areaCode ? { area_code: areaCode } : {})
      setResults(numbers)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Number search failed')
    } finally {
      setSearching(false)
    }
  }

  async function handleBuy(phoneNumber: string) {
    if (forwardTo.replace(/\D/g, '').length < 10) {
      setError('Enter your business phone (10 digits) first — that’s where calls forward to.')
      return
    }
    setBuying(phoneNumber)
    setError(null)
    try {
      await purchaseCallNumber(phoneNumber, forwardTo)
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
      await updateCallSettings(editForward)
      await load()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not save')
    } finally {
      setSaving(false)
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

  return (
    <section>
      <h2 className="t-eyebrow" style={{ marginBottom: 6 }}>Call tracking</h2>
      <p style={{ fontSize: 13, color: 'var(--color-ink-400)', margin: '0 0 12px' }}>
        A dedicated local number that forwards to your real phone. Every inbound call is
        logged on the caller&apos;s record, unknown callers become new leads automatically,
        and missed calls drop an urgent call-back task on your plate.
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
          </div>
        ) : (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <input
                value={forwardTo}
                onChange={e => setForwardTo(e.target.value)}
                placeholder="Your business phone"
                style={{ ...inputStyle, width: 170 }}
              />
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
