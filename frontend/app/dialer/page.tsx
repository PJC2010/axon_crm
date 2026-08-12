'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { AlertTriangle, ArrowLeft, Home, List, Moon, SkipForward, Zap } from 'lucide-react'
import { getCallSettings, getDialerQueue, logDisposition } from '@/lib/api'
import { AuthGuard } from '@/components/AuthGuard'
import { ModuleGate, ScoringQuotaBanner } from '@/components/ModuleGate'
import { ConfirmModal } from '@/components/ConfirmModal'
import { ToastStack, useToast } from '@/components/Toast'
import { useTerminology } from '@/hooks/useTerminology'
import { useTwilioDevice } from '@/hooks/useTwilioDevice'
import { DialerLeadCard } from '@/components/dialer/DialerLeadCard'
import { CallControls } from '@/components/dialer/CallControls'
import { DispositionBar } from '@/components/dialer/DispositionBar'
import { QueueList } from '@/components/dialer/QueueList'
import type { CallDisposition, CallSettings, DialerQueueItem, DialerQueueResponse, ScoreGrade } from '@/lib/types'

const AUTO_ADVANCE_KEY = 'dialer_auto_advance'
const AUTO_ADVANCE_SECONDS = 3
const CONNECTS: CallDisposition[] = ['interested', 'not_interested', 'callback']

const DISPOSITION_LABEL: Record<CallDisposition, string> = {
  no_answer: 'No answer', voicemail: 'Left voicemail', interested: 'Interested',
  not_interested: 'Not interested', callback: 'Callback scheduled',
  wrong_number: 'Wrong number', do_not_call: 'Do not call',
}

function DialerPage() {
  const { toasts, show, dismiss } = useToast()
  const { t } = useTerminology()

  const [settings, setSettings] = useState<CallSettings | null>(null)
  const [resp, setResp] = useState<DialerQueueResponse | null>(null)
  const [items, setItems] = useState<DialerQueueItem[]>([])
  const [idx, setIdx] = useState(0)
  const [skipped, setSkipped] = useState<Set<number>>(new Set())
  // Lazy initializers are browser-only by construction: AuthGuard renders null
  // until its client-side token check passes, so this component never renders
  // during prerender. ?grade= deep links are read here directly (the
  // settings-page convention — no useSearchParams Suspense dance).
  const [grade, setGrade] = useState<'' | ScoreGrade>(() => {
    if (typeof window === 'undefined') return ''
    const g = new URLSearchParams(window.location.search).get('grade') || ''
    return (['A', 'B', 'C', 'D'].includes(g) ? g : '') as '' | ScoreGrade
  })
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [notes, setNotes] = useState('')
  const [phoneChoice, setPhoneChoice] = useState<'primary' | 'alt'>('primary')
  const [autoAdvance, setAutoAdvance] = useState(() =>
    typeof window === 'undefined' || localStorage.getItem(AUTO_ADVANCE_KEY) !== 'off')
  const [countdown, setCountdown] = useState<number | null>(null)
  const [confirmDnc, setConfirmDnc] = useState(false)
  const [stats, setStats] = useState({ calls_today: 0, connects_today: 0 })

  const countdownTimer = useRef<ReturnType<typeof setInterval> | null>(null)
  const shownDeviceError = useRef<string | null>(null)

  const voiceDialing = resp?.voice_dialing ?? settings?.voice_dialing ?? false
  const device = useTwilioDevice(voiceDialing)

  const cancelCountdown = useCallback(() => {
    if (countdownTimer.current) { clearInterval(countdownTimer.current); countdownTimer.current = null }
    setCountdown(null)
  }, [])

  const load = useCallback(async (g: '' | ScoreGrade) => {
    setLoading(true)
    try {
      const q = await getDialerQueue({ grade: g || undefined })
      setResp(q)
      setItems(q.items)
      setStats(q.stats)
      setIdx(0)
      setPhoneChoice('primary')
    } catch (e) {
      show(e instanceof Error ? e.message : 'Could not load the queue', 'error')
    } finally {
      setLoading(false)
    }
  }, [show])

  useEffect(() => {
    getCallSettings().then(setSettings).catch(() => {})
  }, [])

  // The queue tracks the grade filter — including the deep-linked initial one.
  useEffect(() => { load(grade) }, [grade, load])

  // Surface Device/call errors once each (mic denied, token, network).
  useEffect(() => {
    if (device.error && device.error !== shownDeviceError.current) {
      shownDeviceError.current = device.error
      show(device.error, 'error')
    }
  }, [device.error, show])

  useEffect(() => () => cancelCountdown(), [cancelCountdown])

  const current: DialerQueueItem | null = items[idx] ?? null
  const remaining = Math.max(items.length - idx, 0)
  const inCall = device.state === 'connecting' || device.state === 'ringing' || device.state === 'in-call'

  const startCall = useCallback((lead: DialerQueueItem, choice: 'primary' | 'alt') => {
    cancelCountdown()
    device.connect(lead.id, choice)
  }, [device, cancelCountdown])

  /** Move to the next un-skipped lead; refetch when the page is exhausted
   *  (disposed leads sit out the cooldown, so a refetch resumes cleanly). */
  const advance = useCallback((): DialerQueueItem | null => {
    let next = idx + 1
    while (next < items.length && skipped.has(items[next].id)) next++
    if (next >= items.length) {
      load(grade)
      return null
    }
    setIdx(next)
    setPhoneChoice('primary')
    return items[next]
  }, [idx, items, skipped, grade, load])

  const beginAutoAdvance = useCallback((lead: DialerQueueItem) => {
    setCountdown(AUTO_ADVANCE_SECONDS)
    let left = AUTO_ADVANCE_SECONDS
    countdownTimer.current = setInterval(() => {
      left -= 1
      if (left > 0) { setCountdown(left); return }
      if (countdownTimer.current) clearInterval(countdownTimer.current)
      countdownTimer.current = null
      setCountdown(null)
      device.connect(lead.id, 'primary')
    }, 1000)
  }, [device])

  const submitDisposition = useCallback(async (d: CallDisposition, callbackDate?: string) => {
    if (!current) return
    cancelCountdown()
    if (inCall) device.hangup()
    setBusy(true)
    try {
      const base = {
        lead_id: current.id,
        disposition: d,
        phone_choice: phoneChoice,
        ...(notes.trim() ? { notes: notes.trim() } : {}),
        ...(callbackDate ? { callback_due_date: callbackDate } : {}),
      }
      const sid = voiceDialing ? device.activeCallSid : null
      try {
        await logDisposition(sid ? { ...base, call_sid: sid } : base)
      } catch (e) {
        // The webhook may not have landed the call row yet (or the call
        // errored before it existed) — fall back to a manual log.
        if (sid && e instanceof Error && e.message.includes('404')) await logDisposition(base)
        else throw e
      }
      show(`Logged: ${DISPOSITION_LABEL[d]}`)
      setStats(s => ({
        calls_today: s.calls_today + 1,
        connects_today: s.connects_today + (CONNECTS.includes(d) ? 1 : 0),
      }))
      setNotes('')
      const next = advance()
      if (next && autoAdvance && voiceDialing && device.ready) beginAutoAdvance(next)
    } catch (e) {
      show(e instanceof Error ? e.message : 'Could not log the call', 'error')
    } finally {
      setBusy(false)
    }
  }, [current, inCall, device, phoneChoice, notes, voiceDialing, advance, autoAdvance,
      beginAutoAdvance, cancelCountdown, show])

  const handleDisposition = useCallback((d: CallDisposition, callbackDate?: string) => {
    if (d === 'do_not_call') { setConfirmDnc(true); return }
    submitDisposition(d, callbackDate)
  }, [submitDisposition])

  const handleSkip = useCallback(() => {
    if (!current) return
    cancelCountdown()
    setSkipped(prev => new Set(prev).add(current.id))
    let next = idx + 1
    while (next < items.length && (skipped.has(items[next].id) || items[next].id === current.id)) next++
    if (next >= items.length) load(grade)
    else { setIdx(next); setPhoneChoice('primary') }
  }, [current, idx, items, skipped, grade, load, cancelCountdown])

  const handleJump = useCallback((i: number) => {
    cancelCountdown()
    setIdx(i)
    setPhoneChoice('primary')
  }, [cancelCountdown])

  const toggleAutoAdvance = useCallback(() => {
    setAutoAdvance(prev => {
      localStorage.setItem(AUTO_ADVANCE_KEY, prev ? 'off' : 'on')
      return !prev
    })
  }, [])

  const hour = new Date().getHours()
  const quietHours = hour < 8 || hour >= 21

  const telHref = current
    ? (phoneChoice === 'alt' ? current.contact_phone_alt : current.contact_phone)
    : null

  const statBox = (label: string, value: string | number) => (
    <div style={{ flex: 1, padding: '10px 14px', background: 'var(--color-surface)', border: '1px solid var(--color-ink-200)', borderRadius: 'var(--radius-card)' }}>
      <div className="tabular" style={{ fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 600, color: 'var(--color-ink-900)' }}>{value}</div>
      <div style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-ink-400)' }}>{label}</div>
    </div>
  )

  return (
    <div style={{ minHeight: '100vh', background: 'transparent' }}>
      <header style={{
        height: 64, padding: '0 28px', display: 'flex', alignItems: 'center', gap: 16,
        borderBottom: '1px solid var(--color-ink-200)', background: 'var(--color-paper)',
      }}>
        <Link href="/dashboard" className="dash-icon-btn" style={{ textDecoration: 'none', color: 'inherit' }}>
          <ArrowLeft size={15} strokeWidth={1.5} />
        </Link>
        <Link href="/home" title="Home" className="dash-icon-btn" style={{ textDecoration: 'none', color: 'inherit' }}>
          <Home size={15} strokeWidth={1.5} />
        </Link>
        <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 600, color: 'var(--color-ink-900)', margin: 0 }}>
          Dialer
        </h1>
        <div style={{ display: 'flex', gap: 6 }}>
          {(['', 'A', 'B', 'C', 'D'] as const).map(g => (
            <button
              key={g || 'all'}
              onClick={() => { cancelCountdown(); setSkipped(new Set()); setGrade(g) }}
              style={{
                padding: '5px 11px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
                borderRadius: 'var(--radius-button)', border: '1px solid var(--color-ink-200)',
                background: grade === g ? 'var(--color-accent)' : 'var(--color-surface)',
                color: grade === g ? 'var(--color-cream)' : 'var(--color-ink-900)',
              }}
            >
              {g || 'All'}
            </button>
          ))}
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 14 }}>
          <button
            onClick={toggleAutoAdvance}
            title="After logging an outcome, automatically dial the next lead"
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6, padding: '5px 11px',
              fontSize: 12, fontWeight: 600, cursor: 'pointer',
              borderRadius: 'var(--radius-button)', border: '1px solid var(--color-ink-200)',
              background: autoAdvance ? 'var(--color-success-bg)' : 'var(--color-surface)',
              color: autoAdvance ? 'var(--color-success)' : 'var(--color-ink-600)',
            }}
          >
            <Zap size={12} strokeWidth={2} /> Auto-advance {autoAdvance ? 'on' : 'off'}
          </button>
          <Link href="/calls" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12.5, color: 'var(--color-ink-600)', textDecoration: 'none' }}>
            <List size={13} strokeWidth={1.5} /> Call log
          </Link>
        </div>
      </header>

      <div style={{ maxWidth: 1020, margin: '0 auto', padding: '24px 20px' }}>
        {quietHours && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 8, padding: '9px 14px', marginBottom: 16,
            fontSize: 13, color: 'var(--color-ink-700)', background: 'var(--color-gold-soft)',
            border: '1px solid var(--color-ink-200)', borderRadius: 'var(--radius-card)',
          }}>
            <Moon size={14} strokeWidth={1.5} />
            It&apos;s outside typical calling hours (8am–9pm). Cold calls now may annoy — or violate
            calling rules — depending on the {t('lead')}&apos;s local time.
          </div>
        )}

        <ScoringQuotaBanner quota={resp?.scoring_quota} />
        {(resp?.masked_count ?? 0) > 0 && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 8, padding: '9px 14px', marginBottom: 16,
            fontSize: 13, color: 'var(--color-ink-600)', background: 'var(--color-surface)',
            border: '1px solid var(--color-ink-200)', borderRadius: 'var(--radius-card)',
          }}>
            <AlertTriangle size={14} strokeWidth={1.5} style={{ color: 'var(--color-gold)' }} />
            {resp!.masked_count} {resp!.masked_count === 1 ? t('lead') : t('leads')} hidden by your
            plan&apos;s monthly scored-{t('lead')} allowance.
          </div>
        )}

        <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
          {statBox('Calls today', stats.calls_today)}
          {statBox('Connects', stats.connects_today)}
          {statBox('In queue', loading ? '…' : remaining)}
        </div>

        {loading ? (
          <p style={{ color: 'var(--color-ink-400)', fontSize: 13 }}>Loading the queue…</p>
        ) : !current ? (
          <div style={{
            padding: '40px 24px', textAlign: 'center', background: 'var(--color-surface)',
            border: '1px solid var(--color-ink-200)', borderRadius: 'var(--radius-card)',
          }}>
            <p style={{ fontSize: 15, fontWeight: 600, color: 'var(--color-ink-900)', margin: '0 0 6px' }}>
              You&apos;re all caught up.
            </p>
            <p style={{ fontSize: 13, color: 'var(--color-ink-600)', margin: 0 }}>
              No callable {t('leads')} match this filter right now — recently dialed {t('leads')} sit
              out a short cooldown. Try another grade, or check back after the next scoring run.
            </p>
          </div>
        ) : (
          <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 440px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 14 }}>
              <DialerLeadCard lead={current} phoneChoice={phoneChoice} onPhoneChoice={setPhoneChoice} />

              <div style={{
                background: 'var(--color-surface)', border: '1px solid var(--color-ink-200)',
                borderRadius: 'var(--radius-card)', padding: '14px 20px',
                display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
              }}>
                <CallControls
                  voiceDialing={voiceDialing && device.ready}
                  state={device.state}
                  muted={device.muted}
                  elapsedSec={device.elapsedSec}
                  telHref={telHref}
                  onCall={() => startCall(current, phoneChoice)}
                  onHangup={device.hangup}
                  onToggleMute={device.toggleMute}
                />
                <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
                  {countdown !== null && (
                    <button
                      onClick={cancelCountdown}
                      className="dash-icon-btn"
                      style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--color-moss)' }}
                    >
                      Dialing next in {countdown}s — cancel
                    </button>
                  )}
                  <button
                    onClick={handleSkip}
                    disabled={busy || inCall}
                    className="dash-icon-btn"
                    title="Move on without logging anything"
                    style={{ fontSize: 12.5 }}
                  >
                    <SkipForward size={13} strokeWidth={1.5} /> Skip
                  </button>
                </div>
              </div>

              <div style={{
                background: 'var(--color-surface)', border: '1px solid var(--color-ink-200)',
                borderRadius: 'var(--radius-card)', padding: '14px 20px',
              }}>
                <DispositionBar
                  disabled={busy}
                  notes={notes}
                  onNotes={setNotes}
                  onSubmit={handleDisposition}
                />
              </div>
            </div>

            <div style={{ flex: '0 1 300px', minWidth: 260 }}>
              <QueueList items={items} currentIdx={idx} skipped={skipped} onJump={handleJump} />
            </div>
          </div>
        )}
      </div>

      {confirmDnc && current && (
        <ConfirmModal
          title="Flag as do-not-call?"
          message={`${current.contact_name || current.owner_name || 'This ' + t('lead')} will be removed from every future call queue. You can undo this from the ${t('lead')}'s contact details.`}
          confirmLabel="Flag do-not-call"
          danger
          loading={busy}
          onConfirm={() => { setConfirmDnc(false); submitDisposition('do_not_call') }}
          onCancel={() => setConfirmDnc(false)}
        />
      )}

      <ToastStack toasts={toasts} onDismiss={dismiss} />
    </div>
  )
}

export default function DialerPageGuarded() {
  return (
    <AuthGuard>
      <ModuleGate module="calls" feature="Power dialer">
        <DialerPage />
      </ModuleGate>
    </AuthGuard>
  )
}
