'use client'

/**
 * Chat-style message bubble, shared by the activity timeline (ActivityPanel)
 * and the lead's SMS conversation thread (MessageSection). Inbound messages sit
 * left on paper; outbound sit right tinted with the accent color.
 */
export function MessageBubble({
  body,
  inbound,
  channel,
  caption,
}: {
  body: string
  inbound: boolean
  channel?: 'sms' | 'email' | null
  /** Extra caption text (e.g. a timestamp) appended after the channel label. */
  caption?: string
}) {
  const label = channel === 'email'
    ? (inbound ? 'Email received' : 'Email sent')
    : (inbound ? 'Text received' : 'Text sent')
  return (
    <div style={{ display: 'flex', justifyContent: inbound ? 'flex-start' : 'flex-end' }}>
      <div style={{ maxWidth: '85%' }}>
        <p style={{
          fontSize: 13,
          lineHeight: 1.5,
          margin: 0,
          padding: '8px 12px',
          borderRadius: 'var(--radius-card)',
          whiteSpace: 'pre-wrap',
          overflowWrap: 'break-word',
          background: inbound
            ? 'var(--color-paper)'
            : 'color-mix(in srgb, var(--color-accent) 12%, transparent)',
          border: inbound
            ? '1px solid var(--color-ink-200)'
            : '1px solid color-mix(in srgb, var(--color-accent) 25%, transparent)',
          color: 'var(--color-ink-900)',
        }}>
          {body}
        </p>
        <p style={{ fontSize: 10, color: 'var(--color-ink-400)', margin: '3px 2px 0', textAlign: inbound ? 'left' : 'right', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
          {label}{caption ? ` · ${caption}` : ''}
        </p>
      </div>
    </div>
  )
}
