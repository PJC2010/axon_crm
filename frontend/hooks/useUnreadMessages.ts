'use client'
import { useEffect, useState } from 'react'
import { getUnreadMessages } from '@/lib/api'
import type { UnreadMessagesResponse } from '@/lib/types'

/**
 * Account-wide unread inbound SMS state, shared by the header MessageBell and
 * anything else that needs it. Follows the useEntitlements idiom: a
 * module-level cache plus listeners, with a single poller ref-counted across
 * mounted consumers (a page typically mounts two bells — desktop and mobile
 * headers share one interval).
 */
const EMPTY: UnreadMessagesResponse = { count: 0, leads: [] }
const POLL_MS = 30_000

let cache: UnreadMessagesResponse | null = null
const listeners = new Set<(u: UnreadMessagesResponse) => void>()
let mounts = 0
let timer: ReturnType<typeof setInterval> | null = null

async function fetchOnce(): Promise<void> {
  try {
    const data = await getUnreadMessages()
    cache = data
    listeners.forEach((l) => l(data))
  } catch { /* not authenticated yet / transient — keep last state */ }
}

/** Re-fetch now and push to every consumer — called after a conversation is
 *  read or a reply is sent, so the bell clears without waiting for the poll. */
export function refreshUnreadMessages(): void {
  void fetchOnce()
}

export function useUnreadMessages(): UnreadMessagesResponse {
  const [data, setData] = useState<UnreadMessagesResponse>(cache ?? EMPTY)

  useEffect(() => {
    const listener = (u: UnreadMessagesResponse) => setData(u)
    listeners.add(listener)
    mounts += 1
    if (mounts === 1) {
      void fetchOnce()
      timer = setInterval(() => void fetchOnce(), POLL_MS)
    }
    return () => {
      listeners.delete(listener)
      mounts -= 1
      if (mounts === 0 && timer) {
        clearInterval(timer)
        timer = null
      }
    }
  }, [])

  return data
}
