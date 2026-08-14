'use client'

import { useState, type FormEvent } from 'react'
import { Check, Mail } from 'lucide-react'
import { submitProspect } from '@/lib/api'

// Email capture used on the public landing page and the /preview demo.
// Optional by design — the landing page promises "no email required to look",
// so this only ever asks, never gates.
export function ProspectCaptureForm({ source, dark = false }: { source: 'landing' | 'preview'; dark?: boolean }) {
  const [email, setEmail] = useState('')
  const [status, setStatus] = useState<'idle' | 'sending' | 'done' | 'error'>('idle')

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!email.trim() || status === 'sending') return
    setStatus('sending')
    try {
      await submitProspect(email.trim(), undefined, source)
      setStatus('done')
    } catch {
      setStatus('error')
    }
  }

  const inputStyle: React.CSSProperties = dark
    ? { background: 'rgba(255,255,255,0.1)', border: '1px solid rgba(255,255,255,0.25)', color: '#fff' }
    : { background: '#fff', border: '1px solid #d6d3cc', color: '#16181d' }

  if (status === 'done') {
    return (
      <p style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'center', fontWeight: 600, color: dark ? '#fff' : '#1a5a75', margin: 0 }}>
        <Check size={18} strokeWidth={1.5} /> Thanks — you&apos;ll hear back shortly.
      </p>
    )
  }

  return (
    <form onSubmit={onSubmit} style={{ display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap', maxWidth: 460, margin: '0 auto' }}>
      <label htmlFor={`prospect-email-${source}`} style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>
        Email address
      </label>
      <input
        id={`prospect-email-${source}`}
        type="email"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="you@company.com"
        style={{ ...inputStyle, flex: '1 1 220px', padding: '11px 14px', borderRadius: 6, fontSize: 15, outline: 'none' }}
      />
      <button
        type="submit"
        disabled={status === 'sending'}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 8, cursor: 'pointer', border: 'none',
          background: '#1a5a75', color: '#fff', fontWeight: 600, fontSize: 15,
          padding: '11px 20px', borderRadius: 6, opacity: status === 'sending' ? 0.7 : 1,
        }}
      >
        <Mail size={16} strokeWidth={1.5} />
        {status === 'sending' ? 'Sending…' : 'Get a Walkthrough'}
      </button>
      {status === 'error' && (
        <p style={{ flexBasis: '100%', margin: '4px 0 0', fontSize: 13, color: dark ? '#ffb4a8' : '#b3402e', textAlign: 'center' }}>
          Something went wrong — try again, or email admin@axonhtx.com.
        </p>
      )}
    </form>
  )
}
