'use client'
import { useState } from 'react'
import { ArrowRight, ArrowLeft, Zap, MapPin, Kanban, CheckCircle2 } from 'lucide-react'
import { completeOnboarding, triggerRun, seedWorkflowDefaults } from '@/lib/api'

interface Props {
  onComplete: () => void
}

const VERTICALS = [
  { key: 'epoxy_flooring', label: 'Epoxy Flooring', desc: 'Garage floor coatings & concrete finishing' },
  { key: 'pool_maintenance', label: 'Pool Maintenance', desc: 'Pool cleaning, repair & maintenance' },
  { key: 'solar', label: 'Solar', desc: 'Solar panel installation & consultation' },
  { key: 'roofing', label: 'Roofing', desc: 'Roof replacement, repair & storm restoration' },
  { key: 'hvac', label: 'HVAC', desc: 'Heating & cooling install, repair & service' },
  { key: 'fencing', label: 'Fencing', desc: 'Fence installation & replacement' },
  { key: 'landscaping', label: 'Landscaping', desc: 'Landscape design & recurring lawn care' },
  { key: 'pressure_washing', label: 'Pressure Washing', desc: 'Exterior, driveway & pool deck cleaning' },
]

const STEPS = ['Welcome', 'Territory', 'Automations', 'Ready']

export function OnboardingWizard({ onComplete }: Props) {
  const [step, setStep] = useState(0)
  const [vertical, setVertical] = useState('')
  const [zip, setZip] = useState('')
  const [importing, setImporting] = useState(false)
  const [imported, setImported] = useState(false)
  const [seeding, setSeeding] = useState(false)
  const [seeded, setSeeded] = useState(false)
  const [finishing, setFinishing] = useState(false)

  async function handleImport() {
    if (!zip.trim()) return
    setImporting(true)
    try {
      await triggerRun(zip.trim(), vertical || undefined)
      setImported(true)
    } catch { /* allow continuing */ }
    finally { setImporting(false) }
  }

  async function handleSeedWorkflows() {
    if (!vertical) return
    setSeeding(true)
    try {
      await seedWorkflowDefaults(vertical)
      setSeeded(true)
    } catch { /* allow continuing */ }
    finally { setSeeding(false) }
  }

  async function handleFinish() {
    setFinishing(true)
    try {
      await completeOnboarding()
      onComplete()
    } catch {
      onComplete()
    }
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 100,
      background: 'var(--color-paper)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div style={{ width: '100%', maxWidth: 520, padding: '0 20px' }}>
        {/* Progress */}
        <div style={{ display: 'flex', gap: 6, marginBottom: 32, justifyContent: 'center' }}>
          {STEPS.map((s, i) => (
            <div key={s} style={{
              height: 4, width: 48, borderRadius: 2,
              background: i <= step ? 'var(--color-accent)' : 'var(--color-ink-200)',
              transition: 'background 0.3s',
            }} />
          ))}
        </div>

        {/* Step 0: Welcome */}
        {step === 0 && (
          <div style={{ textAlign: 'center' }}>
            <svg width="48" height="48" viewBox="0 0 32 32" fill="none" style={{ marginBottom: 20 }} aria-hidden="true">
              <mask id="axon-mark-onboard">
                <rect width="32" height="32" fill="white" />
                <rect x="2" y="14.5" width="28" height="3" rx="1.5" fill="black" />
                <rect x="14.5" y="2" width="3" height="28" rx="1.5" fill="black" />
              </mask>
              <polygon points="16,5 27,16 16,27 5,16" fill="var(--color-accent)" mask="url(#axon-mark-onboard)" />
              <circle cx="16" cy="16" r="1.5" fill="var(--color-ink-900)" />
            </svg>
            <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 28, fontWeight: 600, color: 'var(--color-ink-900)', margin: '0 0 8px' }}>
              Welcome to Axon
            </h1>
            <p style={{ fontSize: 15, color: 'var(--color-ink-500)', margin: '0 0 28px', lineHeight: 1.5 }}>
              Let&apos;s get your pipeline set up in under a minute. First, what type of service business are you in?
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {VERTICALS.map(v => (
                <button
                  key={v.key}
                  onClick={() => setVertical(v.key)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 12, padding: '14px 18px',
                    borderRadius: 'var(--radius-card)',
                    border: vertical === v.key ? '2px solid var(--color-accent)' : '1px solid var(--color-ink-200)',
                    background: vertical === v.key ? 'color-mix(in srgb, var(--color-accent) 6%, white)' : 'white',
                    cursor: 'pointer', textAlign: 'left', width: '100%',
                  }}
                >
                  <div style={{ flex: 1 }}>
                    <p style={{ margin: 0, fontSize: 15, fontWeight: 500, color: 'var(--color-ink-900)' }}>{v.label}</p>
                    <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--color-ink-400)' }}>{v.desc}</p>
                  </div>
                  {vertical === v.key && <CheckCircle2 size={18} strokeWidth={2} style={{ color: 'var(--color-accent)', flexShrink: 0 }} />}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Step 1: Territory */}
        {step === 1 && (
          <div style={{ textAlign: 'center' }}>
            <MapPin size={40} strokeWidth={1.5} style={{ color: 'var(--color-accent)', marginBottom: 16 }} />
            <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 24, fontWeight: 600, color: 'var(--color-ink-900)', margin: '0 0 8px' }}>
              Set your territory
            </h2>
            <p style={{ fontSize: 15, color: 'var(--color-ink-500)', margin: '0 0 24px', lineHeight: 1.5 }}>
              Enter a ZIP code to import leads. We&apos;ll find properties in your area and score them for{' '}
              {VERTICALS.find(v => v.key === vertical)?.label?.toLowerCase() ?? 'your service'}.
            </p>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'center', alignItems: 'center' }}>
              <input
                type="text"
                value={zip}
                onChange={e => setZip(e.target.value)}
                placeholder="ZIP code (e.g. 77024)"
                style={{
                  width: 200, fontSize: 15, padding: '10px 14px',
                  borderRadius: 'var(--radius-input)', border: '1px solid var(--color-ink-200)',
                  background: 'white', color: 'var(--color-ink-900)', fontFamily: 'var(--font-sans)',
                  outline: 'none', textAlign: 'center',
                }}
              />
              <button
                onClick={handleImport}
                disabled={importing || !zip.trim()}
                style={{
                  padding: '10px 20px', borderRadius: 'var(--radius-pill)',
                  background: imported ? 'var(--color-moss)' : 'var(--color-ink-900)',
                  color: 'white', border: 'none', fontSize: 14, fontWeight: 500, cursor: importing ? 'not-allowed' : 'pointer',
                  display: 'flex', alignItems: 'center', gap: 6,
                }}
              >
                {imported ? (
                  <><CheckCircle2 size={14} /> Importing…</>
                ) : importing ? 'Starting…' : 'Import leads'}
              </button>
            </div>
            {imported && (
              <p style={{ marginTop: 16, fontSize: 13, color: 'var(--color-moss)' }}>
                Pipeline started! Your leads will appear on the dashboard shortly.
              </p>
            )}
          </div>
        )}

        {/* Step 2: Automations */}
        {step === 2 && (
          <div style={{ textAlign: 'center' }}>
            <Zap size={40} strokeWidth={1.5} style={{ color: 'var(--color-accent)', marginBottom: 16 }} />
            <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 24, fontWeight: 600, color: 'var(--color-ink-900)', margin: '0 0 8px' }}>
              Enable automations
            </h2>
            <p style={{ fontSize: 15, color: 'var(--color-ink-500)', margin: '0 0 24px', lineHeight: 1.5 }}>
              Axon can automatically create follow-up tasks when you move leads through your pipeline.
              We&apos;ll set up recommended automations for {VERTICALS.find(v => v.key === vertical)?.label?.toLowerCase() ?? 'your service'}.
            </p>
            <button
              onClick={handleSeedWorkflows}
              disabled={seeding || seeded || !vertical}
              style={{
                padding: '12px 24px', borderRadius: 'var(--radius-pill)',
                background: seeded ? 'var(--color-moss)' : 'var(--color-accent)',
                color: 'white', border: 'none', fontSize: 15, fontWeight: 500, cursor: seeding ? 'not-allowed' : 'pointer',
                display: 'inline-flex', alignItems: 'center', gap: 8,
              }}
            >
              {seeded ? (
                <><CheckCircle2 size={16} /> Automations enabled</>
              ) : seeding ? 'Setting up…' : (
                <><Zap size={16} /> Enable recommended automations</>
              )}
            </button>
            {!vertical && (
              <p style={{ marginTop: 12, fontSize: 13, color: 'var(--color-ink-400)' }}>
                Go back and select a vertical to enable automations.
              </p>
            )}
          </div>
        )}

        {/* Step 3: Ready */}
        {step === 3 && (
          <div style={{ textAlign: 'center' }}>
            <CheckCircle2 size={48} strokeWidth={1.5} style={{ color: 'var(--color-moss)', marginBottom: 16 }} />
            <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 28, fontWeight: 600, color: 'var(--color-ink-900)', margin: '0 0 8px' }}>
              You&apos;re all set!
            </h2>
            <p style={{ fontSize: 15, color: 'var(--color-ink-500)', margin: '0 0 28px', lineHeight: 1.5 }}>
              Your pipeline is configured and ready to go. Here&apos;s what to do next:
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 28 }}>
              {[
                { icon: <Kanban size={18} strokeWidth={1.5} />, label: 'Review your pipeline', desc: 'See scored leads and start reaching out' },
                { icon: <Zap size={18} strokeWidth={1.5} />, label: 'Watch automations work', desc: 'Move a lead to see tasks auto-created' },
              ].map(item => (
                <div key={item.label} style={{
                  display: 'flex', alignItems: 'center', gap: 12, padding: '14px 18px',
                  borderRadius: 'var(--radius-card)', background: 'white', border: '1px solid var(--color-ink-200)', textAlign: 'left',
                }}>
                  <div style={{ color: 'var(--color-accent)', flexShrink: 0 }}>{item.icon}</div>
                  <div>
                    <p style={{ margin: 0, fontSize: 14, fontWeight: 500, color: 'var(--color-ink-900)' }}>{item.label}</p>
                    <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--color-ink-400)' }}>{item.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Navigation */}
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 32 }}>
          {step > 0 ? (
            <button
              onClick={() => setStep(s => s - 1)}
              style={{
                padding: '10px 20px', borderRadius: 'var(--radius-pill)',
                background: 'transparent', color: 'var(--color-ink-500)',
                border: '1px solid var(--color-ink-200)', fontSize: 14, cursor: 'pointer',
                display: 'flex', alignItems: 'center', gap: 6,
              }}
            >
              <ArrowLeft size={14} /> Back
            </button>
          ) : <div />}

          {step < STEPS.length - 1 ? (
            <button
              onClick={() => setStep(s => s + 1)}
              disabled={step === 0 && !vertical}
              style={{
                padding: '10px 24px', borderRadius: 'var(--radius-pill)',
                background: 'var(--color-ink-900)', color: 'white',
                border: 'none', fontSize: 14, fontWeight: 500, cursor: 'pointer',
                display: 'flex', alignItems: 'center', gap: 6,
                opacity: step === 0 && !vertical ? 0.5 : 1,
              }}
            >
              Continue <ArrowRight size={14} />
            </button>
          ) : (
            <button
              onClick={handleFinish}
              disabled={finishing}
              style={{
                padding: '10px 24px', borderRadius: 'var(--radius-pill)',
                background: 'var(--color-accent)', color: 'white',
                border: 'none', fontSize: 14, fontWeight: 500, cursor: finishing ? 'not-allowed' : 'pointer',
                display: 'flex', alignItems: 'center', gap: 6,
              }}
            >
              {finishing ? 'Loading…' : 'Go to dashboard'} <ArrowRight size={14} />
            </button>
          )}
        </div>

        {/* Skip link */}
        {step < STEPS.length - 1 && (
          <div style={{ textAlign: 'center', marginTop: 16 }}>
            <button
              onClick={handleFinish}
              style={{ background: 'none', border: 'none', fontSize: 13, color: 'var(--color-ink-400)', cursor: 'pointer', textDecoration: 'underline' }}
            >
              Skip setup
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
