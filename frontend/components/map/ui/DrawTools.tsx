'use client'
import { useState } from 'react'
import { Pencil, MapPinPlus, CloudHail, X, Check, Undo2 } from 'lucide-react'
import { overlayBtn, fieldStyle } from './controlStyles'
import { ringAreaSqMeters, formatArea } from '../draw'
import { TOOL_LABEL, type DrawTool, type DrawPending } from '../useDrawTools'

/**
 * Event types the scorer knows how to pay a bonus for.
 *
 * Mirrors `config.GEO_EVENT_BONUS`, which is config-only — no endpoint exposes
 * it — so this list is hand-kept. It degrades safely if it goes stale: the
 * server takes any string and falls back to `GEO_EVENT_DEFAULT_BONUS` for a type
 * it doesn't recognise, so a missing entry costs the right bonus amount, not the
 * event.
 */
const EVENT_TYPES: { value: string; label: string }[] = [
  { value: 'hail_swath', label: 'Hail swath' },
  { value: 'storm', label: 'Storm' },
  { value: 'new_construction', label: 'New construction' },
  { value: 'hoa_sweep', label: 'HOA sweep' },
  { value: 'heat_wave', label: 'Heat wave' },
]

/** The three draw tools, as toolbar pills. */
export function DrawToolbar({
  tool, onPick, touch,
}: {
  tool: DrawTool | null
  onPick: (t: DrawTool) => void
  touch: boolean
}) {
  const items: { key: DrawTool; label: string; icon: React.ReactNode }[] = [
    { key: 'territory', label: 'Territory', icon: <Pencil size={13} strokeWidth={1.5} /> },
    { key: 'event', label: 'Event', icon: <CloudHail size={13} strokeWidth={1.5} /> },
    { key: 'pin', label: 'Drop pin', icon: <MapPinPlus size={13} strokeWidth={1.5} /> },
  ]
  return (
    <>
      {items.map(i => (
        <button
          key={i.key}
          onClick={() => onPick(i.key)}
          aria-pressed={tool === i.key}
          title={TOOL_LABEL[i.key]}
          style={overlayBtn(tool === i.key, touch)}
        >
          {i.icon} {i.label}
        </button>
      ))}
    </>
  )
}

/** What to do while a tool is armed but nothing has been drawn yet. */
export function DrawHint({ tool, onCancel }: { tool: DrawTool; onCancel: () => void }) {
  const text = tool === 'pin'
    ? 'Tap the map where you want to prospect.'
    : 'Tap each corner, then tap the first point again to close the shape.'
  return (
    <div style={{
      position: 'absolute', bottom: 16, left: '50%', transform: 'translateX(-50%)',
      display: 'flex', alignItems: 'center', gap: 10, maxWidth: '92%', zIndex: 3,
      background: 'var(--color-paper)', border: '1px solid var(--color-ink-200)',
      borderRadius: 'var(--radius-pill)', boxShadow: 'var(--shadow-card)',
      padding: '8px 8px 8px 14px', fontSize: 12, color: 'var(--color-ink-700)',
    }}>
      <span>{text}</span>
      <button onClick={onCancel} className="dash-icon-btn borderless" title="Cancel">
        <X size={15} strokeWidth={1.5} />
      </button>
    </div>
  )
}

/**
 * Confirm panel for a finished shape.
 *
 * Saving a territory is the one geo mutation that rescores the whole account
 * **synchronously inside the request** (`PUT /geo/service-area` commits and then
 * calls `rescore_leads` before returning; events use a background helper
 * instead). On a large account that is a long blocking call, so `busy` is not
 * decoration here — the copy says what the wait is for, because a save that
 * looks hung is a save the user clicks twice.
 */
export function DrawConfirm({
  pending, busy, onSave, onRedraw, onCancel,
}: {
  pending: DrawPending
  busy: boolean
  onSave: (opts: { eventType: string; name: string }) => void
  onRedraw: () => void
  onCancel: () => void
}) {
  const [eventType, setEventType] = useState(EVENT_TYPES[0].value)
  const [name, setName] = useState('')

  const area = pending.polygon
    ? formatArea(ringAreaSqMeters(pending.polygon.coordinates[0]))
    : null

  const saveLabel = busy
    ? (pending.tool === 'territory' ? 'Saving & rescoring…' : 'Saving…')
    : pending.tool === 'pin' ? 'Prospect here' : 'Save'

  return (
    <div style={{
      position: 'absolute', bottom: 16, left: '50%', transform: 'translateX(-50%)',
      background: 'var(--color-paper)', border: '1px solid var(--color-ink-200)',
      borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)',
      padding: '12px 14px', maxWidth: '92%', width: 320, zIndex: 3,
      display: 'flex', flexDirection: 'column', gap: 10,
    }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-ink-900)' }}>
          {TOOL_LABEL[pending.tool]}
        </div>
        {area && (
          <div className="tabular" style={{ fontSize: 11, color: 'var(--color-ink-500)' }}>{area}</div>
        )}
      </div>

      {pending.tool === 'territory' && (
        <div style={{ fontSize: 11, color: 'var(--color-ink-500)', lineHeight: 1.4 }}>
          Replaces your current service area and rescores every lead — leads inside
          it score higher.
        </div>
      )}

      {pending.tool === 'event' && (
        <>
          <select
            value={eventType}
            onChange={e => setEventType(e.target.value)}
            aria-label="Event type"
            style={fieldStyle(true)}
          >
            {EVENT_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Name (optional)"
            style={fieldStyle(true)}
          />
        </>
      )}

      {pending.tool === 'pin' && pending.point && (
        <div className="tabular" style={{ fontSize: 11, color: 'var(--color-ink-500)' }}>
          {pending.point[1].toFixed(5)}, {pending.point[0].toFixed(5)}
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <button
          onClick={() => onSave({ eventType, name: name.trim() })}
          disabled={busy}
          style={{
            display: 'flex', alignItems: 'center', gap: 6, padding: '9px 14px', minHeight: 40,
            fontSize: 12, fontWeight: 600, borderRadius: 'var(--radius-pill)', border: 'none',
            cursor: busy ? 'default' : 'pointer', opacity: busy ? 0.6 : 1,
            background: 'var(--color-accent)', color: '#ffffff', flex: 1, justifyContent: 'center',
          }}
        >
          <Check size={13} strokeWidth={2} /> {saveLabel}
        </button>
        <button
          onClick={onRedraw}
          disabled={busy}
          className="dash-icon-btn borderless"
          title="Draw again"
        >
          <Undo2 size={15} strokeWidth={1.5} />
        </button>
        <button onClick={onCancel} disabled={busy} className="dash-icon-btn borderless" title="Cancel">
          <X size={15} strokeWidth={1.5} />
        </button>
      </div>
    </div>
  )
}
