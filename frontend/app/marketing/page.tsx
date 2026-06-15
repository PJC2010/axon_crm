'use client'
import { useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, Home, Settings } from 'lucide-react'
import { AuthGuard } from '@/components/AuthGuard'
import { MarketingInsightsPanel } from '@/components/MarketingInsightsPanel'

const RANGES = [
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
  { days: 365, label: '1 year' },
]

function MarketingPage() {
  const [days, setDays] = useState(90)

  return (
    <div style={{ minHeight: '100vh', background: 'var(--color-paper)' }}>
      <header style={{
        height: 64, padding: '0 28px', display: 'flex', alignItems: 'center', gap: 16,
        borderBottom: '1px solid var(--color-ink-200)', background: 'var(--color-paper)',
      }}>
        <Link href="/home" className="dash-icon-btn" title="Home" style={{ textDecoration: 'none', color: 'inherit' }}>
          <ArrowLeft size={15} strokeWidth={1.5} />
        </Link>
        <Link href="/home" title="Home" className="dash-icon-btn" style={{ textDecoration: 'none', color: 'inherit' }}>
          <Home size={15} strokeWidth={1.5} />
        </Link>
        <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 600, color: 'var(--color-ink-900)', margin: 0, flex: 1 }}>
          Marketing
        </h1>
        <Link href="/settings" className="dash-icon-btn" title="Manage connections" style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, textDecoration: 'none', color: 'inherit' }}>
          <Settings size={14} strokeWidth={1.5} /> Connections
        </Link>
      </header>

      <div style={{ maxWidth: 760, margin: '0 auto', padding: '28px 20px' }}>
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
          <div style={{ display: 'inline-flex', gap: 2, padding: 2, background: 'var(--color-surface)', borderRadius: 'var(--radius-pill)', border: '1px solid var(--color-ink-200)' }}>
            {RANGES.map(r => (
              <button
                key={r.days}
                onClick={() => setDays(r.days)}
                style={{
                  padding: '4px 12px', borderRadius: 'var(--radius-pill)', border: 'none', cursor: 'pointer',
                  fontSize: 12, fontWeight: 500,
                  background: days === r.days ? 'var(--color-accent)' : 'transparent',
                  color: days === r.days ? 'white' : 'var(--color-ink-500)',
                }}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>

        <MarketingInsightsPanel days={days} />
      </div>
    </div>
  )
}

export default function MarketingPageGuarded() {
  return <AuthGuard><MarketingPage /></AuthGuard>
}
