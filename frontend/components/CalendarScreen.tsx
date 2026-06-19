'use client'
import { useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, Home, CalendarDays } from 'lucide-react'
import { AppointmentForm } from './AppointmentForm'
import { CalendarView } from './CalendarView'
import { ToastStack, useToast } from './Toast'

interface Props {
  prefillLeadId?: number
}

export function CalendarScreen({ prefillLeadId }: Props) {
  const [reloadKey, setReloadKey] = useState(0)
  const { toasts, show: showToast, dismiss: dismissToast } = useToast()

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
        <CalendarDays size={18} strokeWidth={1.5} color="var(--color-accent)" />
        <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 600, color: 'var(--color-ink-900)', margin: 0 }}>
          Calendar
        </h1>
      </header>

      <div style={{ maxWidth: 680, margin: '0 auto', padding: '28px 20px' }}>
        <div style={{ marginBottom: 28 }}>
          <h2 className="t-eyebrow" style={{ marginBottom: 10 }}>New appointment</h2>
          <AppointmentForm
            prefillLeadId={prefillLeadId}
            onCreated={() => setReloadKey(k => k + 1)}
            onToast={showToast}
          />
        </div>

        <h2 className="t-eyebrow" style={{ marginBottom: 10 }}>Upcoming</h2>
        <CalendarView reloadKey={reloadKey} onToast={showToast} />
      </div>

      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </div>
  )
}
