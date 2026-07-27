'use client'
import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { MessageSquare } from 'lucide-react'
import { useUnreadMessages } from '@/hooks/useUnreadMessages'
import { fmtDateTime } from './lead/format'

/**
 * Header entry point for two-way texting: a message icon badged with the
 * account's unseen inbound text count, opening a dropdown of the leads those
 * texts belong to. Opening a lead marks its thread read (see MessageSection),
 * which clears the badge. Polls via the shared useUnreadMessages store.
 */
export function MessageBell() {
  const { count, leads } = useUnreadMessages()
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDocClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [open])

  return (
    <div ref={rootRef} style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen(o => !o)}
        className="dash-icon-btn"
        style={{ position: 'relative' }}
        title={count > 0 ? `${count} unread text${count === 1 ? '' : 's'}` : 'Messages'}
        aria-label="Unread messages"
      >
        <MessageSquare size={13} strokeWidth={1.5} />
        {count > 0 && (
          <span style={{
            position: 'absolute',
            top: 2,
            right: 2,
            minWidth: 14,
            height: 14,
            borderRadius: 7,
            background: 'var(--color-danger)',
            color: '#fff',
            fontSize: 9,
            fontWeight: 700,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            lineHeight: 1,
            padding: '0 3px',
          }}>
            {count > 99 ? '99+' : count}
          </span>
        )}
      </button>

      {open && (
        <div style={{
          position: 'absolute',
          top: 'calc(100% + 8px)',
          right: 0,
          width: 300,
          maxWidth: 'calc(100vw - 24px)',
          background: 'var(--color-paper)',
          border: '1px solid var(--color-ink-200)',
          borderRadius: 'var(--radius-card)',
          boxShadow: '0 8px 24px rgba(0,0,0,0.12)',
          zIndex: 60,
          overflow: 'hidden',
        }}>
          <p className="t-eyebrow" style={{ margin: 0, padding: '10px 14px', borderBottom: '1px solid var(--color-ink-100)' }}>
            Unread texts
          </p>
          {leads.length === 0 ? (
            <p style={{ margin: 0, padding: '14px', fontSize: 13, color: 'var(--color-ink-400)' }}>
              No unread texts
            </p>
          ) : (
            <ul style={{ listStyle: 'none', margin: 0, padding: 0, maxHeight: 320, overflowY: 'auto' }}>
              {leads.map(l => (
                <li key={l.lead_id} style={{ borderBottom: '1px solid var(--color-ink-100)' }}>
                  <Link
                    href={`/leads/${l.lead_id}`}
                    onClick={() => setOpen(false)}
                    style={{ display: 'block', padding: '10px 14px', textDecoration: 'none' }}
                  >
                    <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-ink-900)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {l.contact_name || l.address || `Lead #${l.lead_id}`}
                      </span>
                      <span style={{
                        flexShrink: 0,
                        minWidth: 18,
                        height: 18,
                        borderRadius: 9,
                        background: 'var(--color-danger)',
                        color: '#fff',
                        fontSize: 10,
                        fontWeight: 700,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        padding: '0 5px',
                      }}>
                        {l.unseen}
                      </span>
                    </span>
                    {l.last_body && (
                      <span style={{ display: 'block', fontSize: 12, color: 'var(--color-ink-500)', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {l.last_body}
                      </span>
                    )}
                    <span style={{ display: 'block', fontSize: 11, color: 'var(--color-ink-400)', marginTop: 2 }}>
                      {fmtDateTime(l.last_at)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
