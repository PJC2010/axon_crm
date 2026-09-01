'use client'
import Link from 'next/link'
import { X, Archive, ArrowUpRight, MapPin, Zap } from 'lucide-react'
import type { Lead, LeadStatus } from '@/lib/types'
import { archiveLead } from '@/lib/api'
import { useState, type ReactNode } from 'react'
import { useTerminology } from '@/hooks/useTerminology'
import { StatusSelect } from './StatusSelect'
import { ScoreBadge } from './ScoreBadge'
import { ContactInfoSection } from './lead/ContactInfoSection'
import { CustomFieldsSection } from './lead/CustomFieldsSection'
import { MessageSection } from './lead/MessageSection'
import { PoliciesSection } from './lead/PoliciesSection'
import { OrdersSection } from './lead/OrdersSection'
import { AppointmentsSection } from './lead/AppointmentsSection'
import { PropertySignals } from './lead/PropertySignals'
import { WhyThisScore } from './lead/WhyThisScore'
import { ActivityPanel } from './lead/ActivityPanel'
import { MaskedLeadPanel } from './lead/MaskedLeadPanel'
import { NextStepHint } from './NextStepHint'

interface Props {
  lead: Lead | null
  onClose: () => void
  onStatusChange: (id: number, s: LeadStatus) => void
  /** Propagate full-lead updates (contact edits / enrichment) up to the list. */
  onLeadChange?: (lead: Lead) => void
  onToast?: (message: string, variant?: 'success' | 'error') => void
  /**
   * Extra actions for the surface that opened this drawer, rendered under the
   * header. The map uses it for "show neighbors" on a won job; every other call
   * site passes nothing.
   *
   * A slot rather than a bottom-of-map panel because this drawer is
   * `width: min(440px, 100vw)` — full width on a phone — so anything the map
   * floats behind it is unreachable exactly where a rep would use it.
   */
  actions?: (lead: Lead) => ReactNode
}

export function ContactDrawer({ lead, onClose, onStatusChange, onLeadChange, onToast, actions }: Props) {
  const { t, propertyBased } = useTerminology()
  const [archiving, setArchiving] = useState(false)

  if (!lead) return null

  // Property businesses lead with the address; everyone else with the person.
  const addressLine = [lead.address, lead.city, lead.state].filter(Boolean).join(', ')
  const title = propertyBased
    ? (addressLine || lead.contact_name || '—')
    : (lead.contact_name || lead.owner_name || addressLine || '—')

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
        style={{ position: 'fixed', inset: 0, background: 'var(--scrim-soft)', zIndex: 'var(--z-drawer)' }}
        onClick={onClose}
      />

      <aside
        style={{
          position: 'fixed',
          right: 0,
          top: 0,
          height: '100%',
          width: 'min(440px, 100vw)',
          maxWidth: '100vw',
          background: 'var(--color-surface)',
          zIndex: 'var(--z-drawer-surface)',
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
            <p className="t-eyebrow" style={{ marginBottom: 4 }}>
              {[lead.account_number, lead.zip].filter(Boolean).join(' · ')}
            </p>
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
              {title}
            </h2>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10 }}>
              <ScoreBadge grade={lead.score_grade} score={lead.lead_score} />
              <StatusSelect
                leadId={lead.id}
                value={lead.status}
                jobValue={lead.estimated_job_value}
                celebrateLabel={lead.address || lead.contact_name || lead.owner_name}
                onChange={s => onStatusChange(lead.id, s)}
              />
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {lead.nearest_customer_m != null && (
                <RouteFitChip meters={lead.nearest_customer_m} count={lead.customers_within_1600m ?? 0} />
              )}
              {lead.geo_components?.event && (lead.geo_components.event_bonus ?? 0) > 0 && (
                <EventChip
                  name={lead.geo_components.event.name || lead.geo_components.event.type}
                  bonus={lead.geo_components.event_bonus ?? 0}
                />
              )}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 12 }}>
              <Link
                href={`/leads/${lead.id}`}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 4,
                  fontSize: 12, fontWeight: 500, color: 'var(--color-accent-300)', textDecoration: 'none',
                }}
              >
                Open full page <ArrowUpRight size={13} strokeWidth={1.5} />
              </Link>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={handleArchive}
              disabled={archiving}
              className="dash-icon-btn borderless"
              title={`Archive this ${t('lead').toLowerCase()}`}
            >
              <Archive size={16} strokeWidth={1.5} />
            </button>
            <button onClick={onClose} className="dash-icon-btn borderless">
              <X size={16} strokeWidth={1.5} />
            </button>
          </div>
        </div>

        <div style={{ flex: 1, overflowY: 'auto' }}>
          {lead.quota_masked ? (
            // Past the monthly reveal allowance (api/scoring_quota.py): the
            // body is a blurred placeholder + upgrade prompt. The live
            // sections must not mount — they'd render the property facts the
            // mask leaves in the row and fire per-lead fetches.
            <MaskedLeadPanel />
          ) : (
            <>
              {actions && (
                <div style={{ padding: '14px 24px 0' }}>{actions(lead)}</div>
              )}
              <div style={{ padding: '0 24px' }}>
                <NextStepHint status={lead.status} leadId={lead.id} onToast={onToast} />
              </div>
              <ContactInfoSection lead={lead} onSaved={l => onLeadChange?.(l)} onToast={onToast} />
              <CustomFieldsSection key={lead.id} lead={lead} onSaved={l => onLeadChange?.(l)} onToast={onToast} />
              <MessageSection key={`msg-${lead.id}`} leadId={lead.id} />
              <PoliciesSection key={`pol-${lead.id}`} leadId={lead.id} />
              <OrdersSection key={`ord-${lead.id}`} leadId={lead.id} />
              <AppointmentsSection key={`appt-${lead.id}`} leadId={lead.id} />
              {propertyBased && <PropertySignals lead={lead} />}
              {propertyBased && <WhyThisScore leadId={lead.id} />}
              <ActivityPanel leadId={lead.id} contactPhone={lead.contact_phone} />
            </>
          )}
        </div>
      </aside>
    </>
  )
}

// "Route fit" chip (juncto geo layer, Phase 3): how this lead sits relative to the
// tenant's book of business — the plain-language read of the geo proximity/density
// components (e.g. "0.3 mi from 2 active customers").
function RouteFitChip({ meters, count }: { meters: number; count: number }) {
  const miles = meters / 1609.34
  const dist = miles < 0.1 ? `${Math.round(meters)} m` : `${miles.toFixed(1)} mi`
  const label = count > 0
    ? `${dist} from ${count} active customer${count === 1 ? '' : 's'}`
    : `Nearest customer ${dist} away`
  return (
    <div
      title="Distance to your nearest active customer and how many are within ~1 mile"
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6, marginTop: 10,
        padding: '4px 10px', fontSize: 12, fontWeight: 500,
        borderRadius: 'var(--radius-pill)', background: 'var(--color-ink-100)',
        color: 'var(--color-ink-700)',
      }}
    >
      <MapPin size={12} strokeWidth={1.5} /> {label}
    </div>
  )
}

// Event chip (Phase 4): names the active event polygon the lead sits in and the
// score bonus it earned, so the boost is explainable rather than a mystery jump.
function EventChip({ name, bonus }: { name: string; bonus: number }) {
  return (
    <div
      title="This lead sits inside an active event area (e.g. a hail swath), lifting its geo score"
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6, marginTop: 10,
        padding: '4px 10px', fontSize: 12, fontWeight: 500,
        borderRadius: 'var(--radius-pill)', background: 'var(--color-danger)',
        color: '#ffffff',
      }}
    >
      <Zap size={12} strokeWidth={1.5} /> {name} +{Math.round(bonus)}
    </div>
  )
}
