'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { ArrowLeft, Archive } from 'lucide-react'
import type { Lead } from '@/lib/types'
import { getLead, archiveLead } from '@/lib/api'
import { StatusSelect } from './StatusSelect'
import { ScoreBadge } from './ScoreBadge'
import { ToastStack, useToast } from './Toast'
import { ContactInfoSection } from './lead/ContactInfoSection'
import { MessageSection } from './lead/MessageSection'
import { PoliciesSection } from './lead/PoliciesSection'
import { OrdersSection } from './lead/OrdersSection'
import { AppointmentsSection } from './lead/AppointmentsSection'
import { PropertySignals } from './lead/PropertySignals'
import { WhyThisScore } from './lead/WhyThisScore'
import { ActivityPanel } from './lead/ActivityPanel'

export function LeadDetail({ leadId }: { leadId: number }) {
  const router = useRouter()
  const [lead, setLead] = useState<Lead | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [archiving, setArchiving] = useState(false)
  const { toasts, show: showToast, dismiss: dismissToast } = useToast()

  useEffect(() => {
    setLoading(true)
    setError(null)
    getLead(leadId)
      .then(setLead)
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load lead'))
      .finally(() => setLoading(false))
  }, [leadId])

  async function handleArchive() {
    setArchiving(true)
    try {
      await archiveLead(leadId)
      router.push('/dashboard')
    } finally { setArchiving(false) }
  }

  const address = lead
    ? ([lead.address, lead.city, lead.state].filter(Boolean).join(', ') || lead.contact_name || '—')
    : ''

  return (
    <div style={{ minHeight: '100vh', background: 'transparent' }}>
      {/* Top bar */}
      <header
        className="flex items-center"
        style={{
          height: 64,
          padding: '0 28px',
          background: 'var(--color-paper)',
          borderBottom: '1px solid var(--color-ink-200)',
        }}
      >
        <Link
          href="/dashboard"
          className="dash-icon-btn"
          style={{ display: 'flex', alignItems: 'center', gap: 6, textDecoration: 'none', color: 'inherit', fontSize: 13 }}
        >
          <ArrowLeft size={14} strokeWidth={1.5} /> Leads
        </Link>
      </header>

      <main style={{ maxWidth: 720, margin: '0 auto', padding: '24px 16px 64px' }}>
        {loading && <p style={{ color: 'var(--color-ink-400)', fontSize: 14 }}>Loading…</p>}
        {error && <p style={{ color: 'var(--color-danger)', fontSize: 14 }}>{error}</p>}

        {lead && (
          <div
            style={{
              background: 'var(--color-surface)',
              border: '1px solid var(--color-ink-200)',
              borderRadius: 'var(--radius-card)',
              overflow: 'hidden',
            }}
          >
            {/* Lead header */}
            <div
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                justifyContent: 'space-between',
                padding: '24px',
                borderBottom: '1px solid var(--color-ink-200)',
              }}
            >
              <div>
                <p className="t-eyebrow" style={{ marginBottom: 4 }}>{lead.zip}</p>
                <h1
                  style={{
                    fontFamily: 'var(--font-display)',
                    fontSize: 22,
                    fontWeight: 600,
                    color: 'var(--color-ink-900)',
                    lineHeight: 1.2,
                    margin: 0,
                  }}
                >
                  {address}
                </h1>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12 }}>
                  <ScoreBadge grade={lead.score_grade} score={lead.lead_score} />
                  <StatusSelect leadId={lead.id} value={lead.status} onChange={s => setLead({ ...lead, status: s })} />
                </div>
              </div>
              <button
                onClick={handleArchive}
                disabled={archiving}
                className="dash-icon-btn borderless"
                title="Archive this lead"
              >
                <Archive size={16} strokeWidth={1.5} />
              </button>
            </div>

            <ContactInfoSection lead={lead} onSaved={setLead} onToast={showToast} />
            <MessageSection leadId={lead.id} />
            <PoliciesSection leadId={lead.id} />
            <OrdersSection leadId={lead.id} />
            <AppointmentsSection leadId={lead.id} />
            <PropertySignals lead={lead} />
            <WhyThisScore leadId={lead.id} />
            <ActivityPanel leadId={lead.id} />
          </div>
        )}
      </main>

      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </div>
  )
}
