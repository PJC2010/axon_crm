'use client'
import Link from 'next/link'
import { X, Archive, ArrowUpRight } from 'lucide-react'
import type { Lead, LeadStatus } from '@/lib/types'
import { archiveLead } from '@/lib/api'
import { useState } from 'react'
import { StatusSelect } from './StatusSelect'
import { ScoreBadge } from './ScoreBadge'
import { ContactInfoSection } from './lead/ContactInfoSection'
import { PropertySignals } from './lead/PropertySignals'
import { WhyThisScore } from './lead/WhyThisScore'
import { ActivityPanel } from './lead/ActivityPanel'

interface Props {
  lead: Lead | null
  onClose: () => void
  onStatusChange: (id: number, s: LeadStatus) => void
  /** Propagate full-lead updates (contact edits / enrichment) up to the list. */
  onLeadChange?: (lead: Lead) => void
  onToast?: (message: string, variant?: 'success' | 'error') => void
}

export function ContactDrawer({ lead, onClose, onStatusChange, onLeadChange, onToast }: Props) {
  const [archiving, setArchiving] = useState(false)

  if (!lead) return null

  const address = [lead.address, lead.city, lead.state].filter(Boolean).join(', ') || lead.contact_name || '—'

  async function handleArchive() {
    if (!lead) return
    setArchiving(true)
    try {
      await archiveLead(lead.id)
      onClose()
    } finally { setArchiving(false) }
  }

  return (
    <>
      {/* Backdrop — 32% ink per design system */}
      <div
        style={{ position: 'fixed', inset: 0, background: 'rgba(22,24,29,0.32)', zIndex: 40 }}
        onClick={onClose}
      />

      <aside
        style={{
          position: 'fixed',
          right: 0,
          top: 0,
          height: '100%',
          width: 440,
          background: 'white',
          zIndex: 50,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          boxShadow: 'var(--shadow-drawer)',
        }}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            padding: '20px 24px',
            borderBottom: '1px solid var(--color-ink-200)',
            flexShrink: 0,
          }}
        >
          <div>
            <p className="t-eyebrow" style={{ marginBottom: 4 }}>{lead.zip}</p>
            <h2
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 17,
                fontWeight: 600,
                color: 'var(--color-ink-900)',
                lineHeight: 1.2,
                margin: 0,
              }}
            >
              {address}
            </h2>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10 }}>
              <ScoreBadge grade={lead.score_grade} score={lead.lead_score} />
              <StatusSelect leadId={lead.id} value={lead.status} onChange={s => onStatusChange(lead.id, s)} />
            </div>
            <Link
              href={`/leads/${lead.id}`}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 4, marginTop: 12,
                fontSize: 12, fontWeight: 500, color: 'var(--color-accent)', textDecoration: 'none',
              }}
            >
              Open full page <ArrowUpRight size={13} strokeWidth={1.5} />
            </Link>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={handleArchive}
              disabled={archiving}
              className="dash-icon-btn borderless"
              title="Archive this lead"
            >
              <Archive size={16} strokeWidth={1.5} />
            </button>
            <button onClick={onClose} className="dash-icon-btn borderless">
              <X size={16} strokeWidth={1.5} />
            </button>
          </div>
        </div>

        <div style={{ flex: 1, overflowY: 'auto' }}>
          <ContactInfoSection lead={lead} onSaved={l => onLeadChange?.(l)} onToast={onToast} />
          <PropertySignals lead={lead} />
          <WhyThisScore leadId={lead.id} />
          <ActivityPanel leadId={lead.id} />
        </div>
      </aside>
    </>
  )
}
