'use client'
import { useState } from 'react'
import Link from 'next/link'
import { Smartphone, Monitor, ArrowLeft, X, Archive } from 'lucide-react'
import { ScoreBadge } from '@/components/ScoreBadge'
import { StatusSelect } from '@/components/StatusSelect'
import { LeadCard } from '@/components/lead/LeadCard'
import { KanbanCard } from '@/components/KanbanCard'
import { PropertySignals } from '@/components/lead/PropertySignals'
import { WhyThisScore } from '@/components/lead/WhyThisScore'
import {
  PREVIEW_LEADS, PREVIEW_CATEGORIES, PREVIEW_PIPELINE_CARD, PREVIEW_EXPLANATION,
} from '@/lib/previewData'

type Mode = 'mobile' | 'desktop'

const noop = () => {}

/**
 * Dev preview — a no-login gallery of the product's UI components rendered with
 * static fixtures. Open /preview/dev to eyeball lead cards, the drawer, and the
 * "why this score" card at phone and desktop widths without a session or the API.
 * This route is intentionally public and read-only (see lib/previewData.ts).
 */
export default function DevPreviewPage() {
  const [mode, setMode] = useState<Mode>('mobile')
  const frameWidth = mode === 'mobile' ? 390 : 760

  return (
    <div style={{ minHeight: '100vh', background: 'var(--color-paper)' }}>
      {/* Toolbar */}
      <header style={{
        position: 'sticky', top: 0, zIndex: 10,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
        height: 60, padding: '0 16px',
        background: 'var(--color-surface)', borderBottom: '1px solid var(--color-ink-200)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
          <Link href="/preview" className="dash-icon-btn borderless" title="Back to demo" style={{ textDecoration: 'none' }}>
            <ArrowLeft size={16} strokeWidth={1.5} />
          </Link>
          <div style={{ minWidth: 0 }}>
            <p style={{ margin: 0, fontFamily: 'var(--font-display)', fontSize: 16, fontWeight: 600, color: 'var(--color-ink-900)' }}>
              Dev Preview
            </p>
            <p style={{ margin: 0, fontSize: 11, color: 'var(--color-ink-400)' }}>Components · sample data · no login</p>
          </div>
        </div>

        {/* Viewport toggle */}
        <div style={{
          display: 'inline-flex', padding: 3, gap: 2,
          background: 'var(--color-ink-50)', borderRadius: 'var(--radius-pill)',
          border: '1px solid var(--color-ink-200)',
        }}>
          {([['mobile', Smartphone, 'Mobile'], ['desktop', Monitor, 'Desktop']] as const).map(([m, Icon, label]) => {
            const active = mode === m
            return (
              <button
                key={m}
                onClick={() => setMode(m)}
                aria-pressed={active}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 6, minHeight: 34, padding: '0 14px',
                  borderRadius: 'var(--radius-pill)', border: 'none', cursor: 'pointer',
                  background: active ? 'var(--color-accent)' : 'transparent',
                  color: active ? 'white' : 'var(--color-ink-500)',
                  fontSize: 13, fontWeight: 600,
                }}
              >
                <Icon size={14} strokeWidth={1.8} /> {label}
              </button>
            )
          })}
        </div>
      </header>

      <main style={{ padding: '28px 16px 64px', display: 'flex', flexDirection: 'column', gap: 40 }}>
        <Section title="Score badges" note="A–F grade with numeric score. Color + letter + dot stay distinct for colorblind readers.">
          <Frame width={frameWidth}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>
              <ScoreBadge grade="A" score={94} />
              <ScoreBadge grade="B" score={82} />
              <ScoreBadge grade="C" score={68} />
              <ScoreBadge grade="D" score={44} />
              <ScoreBadge grade={null} />
            </div>
          </Frame>
        </Section>

        <Section title="Lead cards (list)" note="The phone-width rendering of the lead list — stacks name, score, status, and value so it reads one-thumb.">
          <Frame width={frameWidth}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {PREVIEW_LEADS.map(lead => (
                <LeadCard
                  key={lead.id}
                  lead={lead}
                  propertyBased
                  categories={PREVIEW_CATEGORIES}
                  selected={false}
                  onToggleSelect={noop}
                  onClick={noop}
                  onStatusChange={noop}
                />
              ))}
            </div>
          </Frame>
        </Section>

        <Section title="Kanban card" note="The pipeline board card. Bigger title and brighter value for scannability.">
          <Frame width={frameWidth}>
            <div style={{ maxWidth: 280 }}>
              <KanbanCard lead={PREVIEW_PIPELINE_CARD} onQuickTask={noop} />
            </div>
          </Frame>
        </Section>

        <Section title="Property signals" note="The facts grid inside the lead drawer.">
          <Frame width={frameWidth}>
            <DrawerSurface>
              <PropertySignals lead={PREVIEW_LEADS[0]} />
            </DrawerSurface>
          </Frame>
        </Section>

        <Section title="Why this score" note="Plain-language verdict + the reasons that lifted the score, readable without knowing how scoring works.">
          <Frame width={frameWidth}>
            <DrawerSurface>
              <WhyThisScore leadId={1} explanation={PREVIEW_EXPLANATION} />
            </DrawerSurface>
          </Frame>
        </Section>

        <Section title="Lead drawer" note="The composed drawer: header + property signals + why this score.">
          <Frame width={frameWidth}>
            <DrawerPreview />
          </Frame>
        </Section>
      </main>
    </div>
  )
}

function Section({ title, note, children }: { title: string; note: string; children: React.ReactNode }) {
  return (
    <section>
      <p style={{ margin: '0 0 2px', fontFamily: 'var(--font-display)', fontSize: 15, fontWeight: 600, color: 'var(--color-ink-900)' }}>
        {title}
      </p>
      <p style={{ margin: '0 0 14px', fontSize: 12.5, color: 'var(--color-ink-400)', maxWidth: 620, lineHeight: 1.5 }}>{note}</p>
      {children}
    </section>
  )
}

/** Constrains a preview to the chosen viewport width, centered, with a faint frame. */
function Frame({ width, children }: { width: number; children: React.ReactNode }) {
  return (
    <div style={{
      width: '100%', maxWidth: width, margin: '0 auto',
      padding: 16, borderRadius: 'var(--radius-card)',
      border: '1px dashed var(--color-ink-200)', background: 'var(--color-canvas-deep)',
    }}>
      {children}
    </div>
  )
}

/** Mimics the drawer's card surface so sections designed for it render in context. */
function DrawerSurface({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      background: 'var(--color-surface)', border: '1px solid var(--color-ink-200)',
      borderRadius: 'var(--radius-card)', overflow: 'hidden',
    }}>
      {children}
    </div>
  )
}

function DrawerPreview() {
  const lead = PREVIEW_LEADS[0]
  const title = [lead.address, lead.city, lead.state].filter(Boolean).join(', ')
  return (
    <DrawerSurface>
      <div style={{
        display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
        padding: '20px 24px', borderBottom: '1px solid var(--color-ink-200)',
      }}>
        <div>
          <p className="t-eyebrow" style={{ marginBottom: 4 }}>
            {[lead.account_number, lead.zip].filter(Boolean).join(' · ')}
          </p>
          <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 17, fontWeight: 600, color: 'var(--color-ink-900)', lineHeight: 1.2, margin: 0 }}>
            {title}
          </h2>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10 }}>
            <ScoreBadge grade={lead.score_grade} score={lead.lead_score} />
            <StatusSelect leadId={lead.id} value={lead.status} />
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <span className="dash-icon-btn borderless" aria-hidden><Archive size={16} strokeWidth={1.5} /></span>
          <span className="dash-icon-btn borderless" aria-hidden><X size={16} strokeWidth={1.5} /></span>
        </div>
      </div>
      <PropertySignals lead={lead} />
      <WhyThisScore leadId={lead.id} explanation={PREVIEW_EXPLANATION} />
    </DrawerSurface>
  )
}
