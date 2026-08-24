'use client'
import { Mail, Phone } from 'lucide-react'
import type { Lead, LeadStatus } from '@/lib/types'
import { ScoreBadge } from '@/components/ScoreBadge'
import { StatusSelect } from '@/components/StatusSelect'
import { PropertySignals } from '@/components/lead/PropertySignals'
import { WhyThisScore } from '@/components/lead/WhyThisScore'
import { DrillDrawer } from '@/components/home/dashboardKit'
import { buildDemoExplanation } from '@/lib/demoData'

interface Props {
  /** The lead to show. Kept non-null through the close animation by the
   *  parent (open goes false first, the lead clears ~250ms later). */
  lead: Lead | null
  open: boolean
  onClose: () => void
  onStatusChange: (id: number, s: LeadStatus) => void
}

/**
 * The demo's lead drawer: the product's own drawer sections — property signals
 * and the plain-language "why this score" — composed inside the design-system
 * slide-over, with a working (demo-local) status control. This is the page the
 * product sells: every score explained, so it must feel real here.
 */
export function DemoLeadDrawer({ lead, open, onClose, onStatusChange }: Props) {
  const shown = lead
  if (!shown) return null
  const title = [shown.address, shown.city].filter(Boolean).join(', ') || shown.owner_name || 'Lead'

  return (
    <DrillDrawer
      open={open}
      onClose={onClose}
      eyebrow={[shown.account_number, shown.zip].filter(Boolean).join(' · ')}
      title={title}
      cta={{ label: 'Start free — get a ranked list like this', href: '/signup' }}
      note="Sample data. Your account scores every property in your own ZIP codes."
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
        <ScoreBadge grade={shown.score_grade} score={shown.lead_score} />
        <StatusSelect
          leadId={shown.id}
          value={shown.status}
          jobValue={shown.estimated_job_value}
          celebrateLabel={shown.address ?? shown.owner_name}
          persist={false}
          onChange={s => onStatusChange(shown.id, s)}
        />
        {shown.estimated_job_value != null && (
          <span className="tabular" style={{ marginLeft: 'auto', fontSize: 14, fontWeight: 700, color: 'var(--color-accent-300)' }}>
            ${shown.estimated_job_value.toLocaleString()} est. job
          </span>
        )}
      </div>

      {(shown.contact_phone || shown.contact_email) && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 16 }}>
          {shown.contact_phone && (
            <span style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--color-ink-700)' }}>
              <Phone size={13} strokeWidth={1.5} color="var(--color-ink-400)" /> {shown.contact_phone}
            </span>
          )}
          {shown.contact_email && (
            <span style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--color-ink-700)' }}>
              <Mail size={13} strokeWidth={1.5} color="var(--color-ink-400)" /> {shown.contact_email}
            </span>
          )}
        </div>
      )}

      <div style={{
        background: 'var(--color-surface)', border: '1px solid var(--color-ink-200)',
        borderRadius: 'var(--radius-card)', overflow: 'hidden', marginBottom: 18,
      }}>
        <PropertySignals lead={shown} />
        <WhyThisScore leadId={shown.id} explanation={buildDemoExplanation(shown)} />
      </div>
    </DrillDrawer>
  )
}
