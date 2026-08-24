'use client'
import { useEffect, useState, type FormEvent } from 'react'
import { X } from 'lucide-react'
import { DEMO_CATEGORIES, DEMO_ZIPS } from '@/lib/demoData'

export interface NewLeadInput {
  name: string
  address: string
  zip: string
  vertical: string
  jobValue: number
}

interface Props {
  onClose: () => void
  onCreate: (input: NewLeadInput) => void
}

const field: React.CSSProperties = {
  width: '100%', minHeight: 44, padding: '0 12px',
  background: 'var(--color-paper)', border: '1px solid var(--color-ink-200)',
  borderRadius: 'var(--radius-button)', fontSize: 14, color: 'var(--color-ink-900)',
  fontFamily: 'var(--font-sans)', outline: 'none',
}

/**
 * "New lead" for the demo: four fields in, a scored lead out. The point is the
 * moment after submit — the visitor's own lead comes back graded, with a
 * "why this score" breakdown, which is the product's whole pitch.
 */
export function DemoNewLeadModal({ onClose, onCreate }: Props) {
  const [name, setName] = useState('')
  const [address, setAddress] = useState('')
  const [zip, setZip] = useState('77008')
  const [vertical, setVertical] = useState(DEMO_CATEGORIES[0].value)
  const [jobValue, setJobValue] = useState('9500')

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  function submit(e: FormEvent) {
    e.preventDefault()
    if (!address.trim()) return
    onCreate({
      name: name.trim(),
      address: address.trim(),
      zip,
      vertical,
      jobValue: Math.max(0, Number(jobValue) || 0),
    })
  }

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 60, display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'rgba(17,20,24,0.55)', backdropFilter: 'blur(2px)', padding: 16,
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="New lead"
        onClick={e => e.stopPropagation()}
        style={{
          width: 'min(420px, 100%)', background: 'var(--color-surface)',
          borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-modal)', overflow: 'hidden',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 20px', borderBottom: '1px solid var(--color-ink-100)' }}>
          <div>
            <p style={{ margin: 0, fontFamily: 'var(--font-display)', fontSize: 17, fontWeight: 600, color: 'var(--color-ink-900)' }}>
              New lead
            </p>
            <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--color-ink-400)' }}>
              Axon scores it the moment it lands.
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            style={{ background: 'none', border: '1px solid var(--color-ink-200)', borderRadius: 'var(--radius-button)', width: 32, height: 32, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', color: 'var(--color-ink-500)' }}
          >
            <X size={15} strokeWidth={1.5} />
          </button>
        </div>

        <form onSubmit={submit} style={{ padding: '18px 20px 20px', display: 'flex', flexDirection: 'column', gap: 12 }}>
          <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-ink-600)' }}>
            Contact name
            <input value={name} onChange={e => setName(e.target.value)} placeholder="Dana Fox" style={{ ...field, marginTop: 4 }} />
          </label>
          <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-ink-600)' }}>
            Street address *
            <input value={address} onChange={e => setAddress(e.target.value)} required placeholder="1200 Oak Ln" style={{ ...field, marginTop: 4 }} />
          </label>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-ink-600)' }}>
              ZIP
              <select value={zip} onChange={e => setZip(e.target.value)} style={{ ...field, marginTop: 4 }}>
                {Object.keys(DEMO_ZIPS).map(z => <option key={z} value={z}>{z}</option>)}
              </select>
            </label>
            <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-ink-600)' }}>
              Est. job value ($)
              <input
                value={jobValue}
                onChange={e => setJobValue(e.target.value)}
                inputMode="numeric"
                pattern="[0-9]*"
                style={{ ...field, marginTop: 4 }}
              />
            </label>
          </div>
          <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-ink-600)' }}>
            Category
            <select value={vertical} onChange={e => setVertical(e.target.value)} style={{ ...field, marginTop: 4 }}>
              {DEMO_CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          </label>
          <button
            type="submit"
            style={{
              marginTop: 4, minHeight: 44, border: 'none', borderRadius: 'var(--radius-button)',
              background: 'var(--color-accent)', color: 'white', fontSize: 14, fontWeight: 700, cursor: 'pointer',
            }}
          >
            Add & score it
          </button>
        </form>
      </div>
    </div>
  )
}
