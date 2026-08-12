'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { Call, Device } from '@twilio/voice-sdk'
import { getDialerToken } from '@/lib/api'

export type DialerCallState = 'idle' | 'connecting' | 'ringing' | 'in-call' | 'ended'

/**
 * Twilio Voice Device lifecycle for the power dialer (browser calling).
 *
 * The SDK is loaded with a dynamic import only when `enabled` — accounts
 * without the server-side TwiML App config never download it, and the dialer
 * page keeps working as a tel: click-through queue. Token comes from
 * POST /api/dialer/token and self-refreshes on the SDK's tokenWillExpire.
 *
 * connect() sends only { lead_id, phone_choice } — the webhook resolves the
 * actual number server-side from the token's own account, so no phone number
 * ever originates in the browser.
 */
export function useTwilioDevice(enabled: boolean) {
  const [ready, setReady] = useState(false)
  const [state, setState] = useState<DialerCallState>('idle')
  const [error, setError] = useState<string | null>(null)
  const [muted, setMuted] = useState(false)
  const [elapsedSec, setElapsedSec] = useState(0)
  const [activeCallSid, setActiveCallSid] = useState<string | null>(null)

  const deviceRef = useRef<Device | null>(null)
  const callRef = useRef<Call | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopTimer = useCallback(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
  }, [])

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    let device: Device | null = null
    ;(async () => {
      try {
        const { token } = await getDialerToken()
        const { Device: TwilioDevice } = await import('@twilio/voice-sdk')
        if (cancelled) return
        device = new TwilioDevice(token, { logLevel: 'error' })
        device.on('error', (err: { message?: string }) => {
          setError(err?.message || 'Browser calling error')
        })
        device.on('tokenWillExpire', async () => {
          try { device?.updateToken((await getDialerToken()).token) }
          catch { /* the next connect() will surface the failure */ }
        })
        deviceRef.current = device
        setReady(true)
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Browser calling unavailable')
      }
    })()
    return () => {
      cancelled = true
      stopTimer()
      callRef.current = null
      deviceRef.current = null
      device?.destroy()
      setReady(false)
      setState('idle')
    }
  }, [enabled, stopTimer])

  const connect = useCallback(async (leadId: number, phoneChoice: 'primary' | 'alt' = 'primary') => {
    const device = deviceRef.current
    if (!device || callRef.current) return
    setError(null)
    setMuted(false)
    setElapsedSec(0)
    setActiveCallSid(null)
    setState('connecting')
    try {
      const call = await device.connect({
        params: { lead_id: String(leadId), phone_choice: phoneChoice },
      })
      callRef.current = call
      const captureSid = () => {
        const sid = call.parameters?.CallSid
        if (sid) setActiveCallSid(sid)
      }
      call.on('ringing', () => { captureSid(); setState('ringing') })
      call.on('accept', () => {
        captureSid()
        setState('in-call')
        stopTimer()
        timerRef.current = setInterval(() => setElapsedSec(s => s + 1), 1000)
      })
      call.on('mute', (isMuted: boolean) => setMuted(isMuted))
      const finish = () => {
        captureSid()
        stopTimer()
        callRef.current = null
        setState('ended')
      }
      call.on('disconnect', finish)
      call.on('cancel', finish)
      call.on('error', (err: { message?: string }) => {
        setError(err?.message || 'Call failed')
        finish()
      })
    } catch (e) {
      // Mic permission denied lands here (NotAllowedError), as do transport
      // failures before the call object exists.
      callRef.current = null
      setState('ended')
      setError(e instanceof Error ? e.message : 'Could not start the call')
    }
  }, [stopTimer])

  const hangup = useCallback(() => {
    callRef.current?.disconnect()
  }, [])

  const toggleMute = useCallback(() => {
    const call = callRef.current
    if (!call) return
    call.mute(!call.isMuted())
  }, [])

  return { ready, state, error, muted, elapsedSec, activeCallSid, connect, hangup, toggleMute }
}
