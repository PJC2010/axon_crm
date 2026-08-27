'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { ArrowLeft, Archive, Phone, MessageSquare, PenLine } from 'lucide-react'
import type { Lead } from '@/lib/types'
import { getLead, archiveLead } from '@/lib/api'
import { useTerminology } from '@/hooks/useTerminology'
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
import { DisqualifyButton } from './lead/DisqualifyButton'

export function LeadDetail({ leadId }: { leadId: number }) {
  const router = useRouter()
  const { propertyBased } = useTerminology()
  const [lead, setLead] = useState<Lead | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [archiving, setArchiving] = useState(false)
  const [wide, setWide] = useState(true)
  const { toasts, show: showToast, dismiss: dismissToast } = useToast()

  useEffect(() => {
    const check = () => setWide(window.innerWidth >= 640)
    check()
    window.addEventListener('resize', check)
    return () => window.removeEventListener('resize', check)
  }, [])

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

  // Property businesses lead with the address; everyone else with the person.
  const addressLine = lead ? [lead.address, lead.city, lead.state].filter(Boolean).join(', ') : ''
  const title = lead
    ? (propertyBased ? (addressLine || lead.contact_name || '—') : (lead.contact_name || lead.owner_name || addressLine || '—'))
    : ''
  const eyebrow = lead ? (propertyBased ? lead.zip : lead.account_number) : null

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

      <main style={{ maxWidth: 720, margin: '0 auto', padding: wide ? '24px 16px 64px' : '24px 16px 110px' }}>
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
                <p className="t-eyebrow" style={{ marginBottom: 4 }}>{eyebrow}</p>
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
                  {title}
                </h1>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12 }}>
                  <ScoreBadge grade={lead.score_grade} score={lead.lead_score} />
                  <StatusSelect
                    leadId={lead.id}
                    value={lead.status}
                    jobValue={lead.estimated_job_value}
                    celebrateLabel={title}
                    onChange={s => setLead({ ...lead, status: s })}
                  />
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <DisqualifyButton
                  leadId={lead.id}
                  onDone={() => showToast('Flagged as a bad lead — thanks, this improves scoring.')}
                />
                <button
                  onClick={handleArchive}
                  disabled={archiving}
                  className="dash-icon-btn borderless"
                  title="Archive this lead"
                >
                  <Archive size={16} strokeWidth={1.5} />
                </button>
              </div>
            </div>

            <ContactInfoSection lead={lead} onSaved={setLead} onToast={showToast} />
            <MessageSection leadId={lead.id} />
            <PoliciesSection leadId={lead.id} />
            <OrdersSection leadId={lead.id} />
            <AppointmentsSection leadId={lead.id} />
            {propertyBased && <PropertySignals lead={lead} />}
            {propertyBased && <WhyThisScore leadId={lead.id} />}
            <div id="lead-activity">
              <ActivityPanel leadId={lead.id} contactPhone={lead.contact_phone} />
            </div>
          </div>
        )}
      </main>

      {/* Sticky one-thumb action bar — contractors work this page from a truck.
          Primary actions stay under the thumb; content gets bottom padding above. */}
      {!wide && lead && (
        <nav
          aria-label="Quick actions"
          style={{
            position: 'fixed', bottom: 0, left: 0, right: 0, zIndex: 50,
            display: 'flex', gap: 8,
            padding: '10px 12px calc(10px + env(safe-area-inset-bottom))',
            background: 'var(--color-paper)',
            borderTop: '1px solid var(--color-ink-200)',
            boxShadow: '0 -4px 16px rgba(0,0,0,0.06)',
          }}
        >
          {lead.contact_phone && (
            <a
              href={`tel:${lead.contact_phone}`}
              style={{
                flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7,
                minHeight: 48, borderRadius: 'var(--radius-pill)',
                background: 'var(--color-accent)', color: 'var(--text-on-accent)',
                fontSize: 14, fontWeight: 600, textDecoration: 'none',
              }}
            >
              <Phone size={15} strokeWidth={2} /> Call
            </a>
          )}
          {lead.contact_phone && (
            <a
              href={`sms:${lead.contact_phone}`}
              style={{
                flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7,
                minHeight: 48, borderRadius: 'var(--radius-pill)',
                background: 'var(--color-surface)', color: 'var(--color-ink-800)',
                border: '1px solid var(--color-ink-300)',
                fontSize: 14, fontWeight: 600, textDecoration: 'none',
              }}
            >
              <MessageSquare size={15} strokeWidth={2} /> Text
            </a>
          )}
          <button
            onClick={() => document.getElementById('lead-activity')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
            style={{
              flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7,
              minHeight: 48, borderRadius: 'var(--radius-pill)',
              background: lead.contact_phone ? 'var(--color-surface)' : 'var(--color-accent)',
              color: lead.contact_phone ? 'var(--color-ink-800)' : 'white',
              border: lead.contact_phone ? '1px solid var(--color-ink-300)' : 'none',
              fontSize: 14, fontWeight: 600, cursor: 'pointer',
            }}
          >
            <PenLine size={15} strokeWidth={2} /> Log it
          </button>
        </nav>
      )}

      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </div>
  )
}
