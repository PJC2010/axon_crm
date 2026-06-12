'use client'

interface Props {
  value: string
  onChange: (iso: string) => void
}

function offsetDate(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}

const PRESETS = [
  { label: 'Today',    days: 0 },
  { label: 'Tomorrow', days: 1 },
  { label: '3 days',   days: 3 },
  { label: 'Next week', days: 7 },
]

export function DateQuickPicks({ value, onChange }: Props) {
  return (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
      {PRESETS.map(p => {
        const iso = offsetDate(p.days)
        const active = value === iso
        return (
          <button
            key={p.label}
            type="button"
            onClick={() => onChange(iso)}
            style={{
              padding: '4px 10px',
              borderRadius: 'var(--radius-pill)',
              border: active
                ? '1.5px solid var(--color-accent)'
                : '1.5px solid var(--color-ink-300)',
              background: active ? 'var(--color-accent)' : 'transparent',
              color: active ? 'white' : 'var(--color-ink-600)',
              fontSize: 12,
              fontWeight: active ? 600 : 400,
              cursor: 'pointer',
              whiteSpace: 'nowrap',
            }}
          >
            {p.label}
          </button>
        )
      })}
    </div>
  )
}
