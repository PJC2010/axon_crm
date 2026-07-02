'use client'
import { useState, useEffect } from 'react'
import { ArrowRight, ArrowLeft, Zap, MapPin, Kanban, CheckCircle2, Briefcase } from 'lucide-react'
import {
  completeOnboarding, triggerRun, seedWorkflowDefaults, getRegions,
  getBusinessTypes, updateBusinessType, type Region,
} from '@/lib/api'
import { useTerminology } from '@/hooks/useTerminology'
import { refreshEntitlements } from '@/hooks/useEntitlements'
import type { BusinessTypeInfo } from '@/lib/types'

interface Props {
  onComplete: () => void
}

export function OnboardingWizard({ onComplete }: Props) {
  // Category picklist + terminology come from the account's business type; a
  // switch on the Business step refreshes them in place (refreshEntitlements).
  const { categories, t, businessType, propertyBased } = useTerminology()
  const categoryLabel = (value: string) => categories.find(c => c.value === value)?.label
  const [step, setStep] = useState(0)
  const [vertical, setVertical] = useState('')

  // Business-type picker (step 0). `bizType` tracks the user's selection before
  // it's applied on Continue; property_based comes from the catalog so the
  // Territory step hides immediately for non-property presets.
  const [catalog, setCatalog] = useState<BusinessTypeInfo[]>([])
  const [bizType, setBizType] = useState<string | null>(null)
  const [applying, setApplying] = useState(false)
  useEffect(() => {
    getBusinessTypes().then(setCatalog).catch(() => setCatalog([]))
  }, [])
  const selectedType = bizType ?? businessType
  const selectedInfo = catalog.find(c => c.key === selectedType)
  const isPropertyBased = selectedInfo?.property_based ?? propertyBased
  const isHomeServices = selectedType === 'home_services'

  const steps = ['Business', 'Category', ...(isPropertyBased ? ['Territory'] : []), 'Automations', 'Ready']
  const stepName = steps[Math.min(step, steps.length - 1)]

  async function handleBusinessContinue() {
    if (bizType && bizType !== businessType) {
      setApplying(true)
      try {
        // apply_defaults seeds the pack (stages, fields, workflows, modules).
        await updateBusinessType(bizType, true)
        await refreshEntitlements()
      } catch { /* allow continuing — terminology falls back to current */ }
      finally { setApplying(false) }
    }
    setVertical('')
    setStep(s => s + 1)
  }
  const [zip, setZip] = useState('')
  const [importing, setImporting] = useState(false)
  const [imported, setImported] = useState(false)
  const [seeding, setSeeding] = useState(false)
  const [seeded, setSeeded] = useState(false)
  const [finishing, setFinishing] = useState(false)

  // Region typeahead (primary territory picker). ZIP entry is the fallback below.
  const [regionQuery, setRegionQuery] = useState('')
  const [regions, setRegions] = useState<Region[]>([])
  const [region, setRegion] = useState<Region | null>(null)
  const [showZip, setShowZip] = useState(false)

  // Debounced region search. Skipped once a region is chosen (query mirrors its name).
  useEffect(() => {
    if (region && regionQuery === region.name) return
    const q = regionQuery.trim()
    if (q.length < 2) { setRegions([]); return }
    const t = setTimeout(() => {
      getRegions(q).then(setRegions).catch(() => setRegions([]))
    }, 250)
    return () => clearTimeout(t)
  }, [regionQuery, region])

  const canImport = region !== null || (showZip && zip.trim().length > 0)

  async function handleImport() {
    if (!canImport) return
    setImporting(true)
    try {
      await triggerRun(region ? { region_id: region.region_id } : { zip: zip.trim() },
        vertical || undefined)
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
          {steps.map((s, i) => (
            <div key={s} style={{
              height: 4, width: 48, borderRadius: 2,
              background: i <= step ? 'var(--color-accent)' : 'var(--color-ink-200)',
              transition: 'background 0.3s',
            }} />
          ))}
        </div>

        {/* Step: Business type */}
        {stepName === 'Business' && (
          <div style={{ textAlign: 'center' }}>
            <Briefcase size={40} strokeWidth={1.5} style={{ color: 'var(--color-accent)', marginBottom: 16 }} />
            <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 28, fontWeight: 600, color: 'var(--color-ink-900)', margin: '0 0 8px' }}>
              Welcome to Axon
            </h1>
            <p style={{ fontSize: 15, color: 'var(--color-ink-500)', margin: '0 0 28px', lineHeight: 1.5 }}>
              What kind of business are you? This sets up your pipeline stages, fields, and automations.
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {catalog.map(c => (
                <button
                  key={c.key}
                  onClick={() => setBizType(c.key)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 12, padding: '14px 18px',
                    borderRadius: 'var(--radius-card)',
                    border: selectedType === c.key ? '2px solid var(--color-accent)' : '1px solid var(--color-ink-200)',
                    background: selectedType === c.key ? 'var(--color-accent-50)' : 'var(--color-surface)',
                    cursor: 'pointer', textAlign: 'left', width: '100%',
                  }}
                >
                  <div style={{ flex: 1 }}>
                    <p style={{ margin: 0, fontSize: 15, fontWeight: 500, color: 'var(--color-ink-900)' }}>{c.label}</p>
                  </div>
                  {selectedType === c.key && <CheckCircle2 size={18} strokeWidth={2} style={{ color: 'var(--color-accent)', flexShrink: 0 }} />}
                </button>
              ))}
              {catalog.length === 0 && (
                <p style={{ fontSize: 13, color: 'var(--color-ink-400)' }}>Loading business types…</p>
              )}
            </div>
          </div>
        )}

        {/* Step: Category */}
        {stepName === 'Category' && (
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
              Pick your {t('category').toLowerCase()}
            </h1>
            <p style={{ fontSize: 15, color: 'var(--color-ink-500)', margin: '0 0 28px', lineHeight: 1.5 }}>
              Which {t('category').toLowerCase()} best describes your work?
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {categories.map(c => (
                <button
                  key={c.value}
                  onClick={() => setVertical(c.value)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 12, padding: '14px 18px',
                    borderRadius: 'var(--radius-card)',
                    border: vertical === c.value ? '2px solid var(--color-accent)' : '1px solid var(--color-ink-200)',
                    background: vertical === c.value ? 'var(--color-accent-50)' : 'var(--color-surface)',
                    cursor: 'pointer', textAlign: 'left', width: '100%',
                  }}
                >
                  <div style={{ flex: 1 }}>
                    <p style={{ margin: 0, fontSize: 15, fontWeight: 500, color: 'var(--color-ink-900)' }}>{c.label}</p>
                  </div>
                  {vertical === c.value && <CheckCircle2 size={18} strokeWidth={2} style={{ color: 'var(--color-accent)', flexShrink: 0 }} />}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Step: Territory (property-based presets only) */}
        {stepName === 'Territory' && (
          <div style={{ textAlign: 'center' }}>
            <MapPin size={40} strokeWidth={1.5} style={{ color: 'var(--color-accent)', marginBottom: 16 }} />
            <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 24, fontWeight: 600, color: 'var(--color-ink-900)', margin: '0 0 8px' }}>
              Set your territory
            </h2>
            <p style={{ fontSize: 15, color: 'var(--color-ink-500)', margin: '0 0 24px', lineHeight: 1.5 }}>
              Pick the area you serve by name — e.g. The Heights or Spring Branch. We&apos;ll find
              properties there and score them for{' '}
              {categoryLabel(vertical)?.toLowerCase() ?? 'your service'}.
            </p>

            {/* Region typeahead (primary) */}
            <div style={{ position: 'relative', maxWidth: 360, margin: '0 auto' }}>
              <input
                type="text"
                value={regionQuery}
                onChange={e => { setRegion(null); setRegionQuery(e.target.value) }}
                placeholder="Search a neighborhood…"
                style={{
                  width: '100%', boxSizing: 'border-box', fontSize: 15, padding: '10px 14px',
                  borderRadius: 'var(--radius-input)',
                  border: region ? '2px solid var(--color-accent)' : '1px solid var(--color-ink-200)',
                  background: 'var(--color-surface)', color: 'var(--color-ink-900)', fontFamily: 'var(--font-sans)',
                  outline: 'none', textAlign: 'left',
                }}
              />
              {!region && regions.length > 0 && (
                <div style={{
                  position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 10, marginTop: 4,
                  background: 'var(--color-surface)', border: '1px solid var(--color-ink-200)',
                  borderRadius: 'var(--radius-card)', boxShadow: '0 8px 24px rgba(0,0,0,0.08)',
                  maxHeight: 240, overflowY: 'auto', textAlign: 'left',
                }}>
                  {regions.map(r => (
                    <button
                      key={r.region_id}
                      onClick={() => { setRegion(r); setRegionQuery(r.name); setRegions([]) }}
                      style={{
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8,
                        width: '100%', padding: '10px 14px', background: 'var(--color-surface)', border: 'none',
                        borderBottom: '1px solid var(--color-ink-100)', cursor: 'pointer', textAlign: 'left',
                      }}
                    >
                      <span style={{ fontSize: 14, color: 'var(--color-ink-900)' }}>{r.name}</span>
                      <span style={{ fontSize: 12, color: 'var(--color-ink-400)', flexShrink: 0 }}>
                        {r.parcel_count.toLocaleString()} properties
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* ZIP fallback (advanced) */}
            <div style={{ marginTop: 14 }}>
              {!showZip ? (
                <button
                  onClick={() => setShowZip(true)}
                  style={{ background: 'none', border: 'none', fontSize: 13, color: 'var(--color-ink-400)', cursor: 'pointer', textDecoration: 'underline' }}
                >
                  Enter a ZIP code instead
                </button>
              ) : (
                <input
                  type="text"
                  value={zip}
                  onChange={e => setZip(e.target.value)}
                  placeholder="ZIP code (e.g. 77024)"
                  style={{
                    width: 200, fontSize: 15, padding: '10px 14px',
                    borderRadius: 'var(--radius-input)', border: '1px solid var(--color-ink-200)',
                    background: 'var(--color-surface)', color: 'var(--color-ink-900)', fontFamily: 'var(--font-sans)',
                    outline: 'none', textAlign: 'center',
                  }}
                />
              )}
            </div>

            <div style={{ marginTop: 18 }}>
              <button
                onClick={handleImport}
                disabled={importing || !canImport}
                style={{
                  padding: '10px 20px', borderRadius: 'var(--radius-pill)',
                  background: imported ? 'var(--color-moss)' : 'var(--color-ink-900)',
                  color: 'white', border: 'none', fontSize: 14, fontWeight: 500,
                  cursor: importing || !canImport ? 'not-allowed' : 'pointer',
                  opacity: !canImport ? 0.5 : 1,
                  display: 'inline-flex', alignItems: 'center', gap: 6,
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

        {/* Step: Automations */}
        {stepName === 'Automations' && (
          <div style={{ textAlign: 'center' }}>
            <Zap size={40} strokeWidth={1.5} style={{ color: 'var(--color-accent)', marginBottom: 16 }} />
            <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 24, fontWeight: 600, color: 'var(--color-ink-900)', margin: '0 0 8px' }}>
              {isHomeServices ? 'Enable automations' : 'Automations are ready'}
            </h2>
            {isHomeServices ? (
              <>
                <p style={{ fontSize: 15, color: 'var(--color-ink-500)', margin: '0 0 24px', lineHeight: 1.5 }}>
                  Axon can automatically create follow-up tasks when you move leads through your pipeline.
                  We&apos;ll set up recommended automations for {categoryLabel(vertical)?.toLowerCase() ?? 'your service'}.
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
              </>
            ) : (
              <>
                <p style={{ fontSize: 15, color: 'var(--color-ink-500)', margin: '0 0 24px', lineHeight: 1.5 }}>
                  Your {selectedInfo?.label.toLowerCase() ?? 'business'} preset already set up its
                  recommended automations{selectedType === 'insurance_agency'
                    ? ' — renewal reminders at 90, 30, and 7 days before each policy expires, plus an annual review nudge.'
                    : selectedType === 'retail'
                      ? ' — a win-back task when a customer goes 90 days without a purchase.'
                      : '.'}
                  {' '}Manage them anytime in Settings.
                </p>
                <div style={{
                  display: 'inline-flex', alignItems: 'center', gap: 8, padding: '12px 24px',
                  borderRadius: 'var(--radius-pill)', background: 'var(--color-moss)', color: 'white',
                  fontSize: 15, fontWeight: 500,
                }}>
                  <CheckCircle2 size={16} /> Automations enabled
                </div>
              </>
            )}
          </div>
        )}

        {/* Step: Ready */}
        {stepName === 'Ready' && (
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
                  borderRadius: 'var(--radius-card)', background: 'var(--color-surface)', border: '1px solid var(--color-ink-200)', textAlign: 'left',
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

          {step < steps.length - 1 ? (
            <button
              onClick={() => stepName === 'Business' ? handleBusinessContinue() : setStep(s => s + 1)}
              disabled={(stepName === 'Category' && !vertical) || applying}
              style={{
                padding: '10px 24px', borderRadius: 'var(--radius-pill)',
                background: 'var(--color-accent)', color: 'white',
                border: 'none', fontSize: 14, fontWeight: 500, cursor: 'pointer',
                display: 'flex', alignItems: 'center', gap: 6,
                opacity: (stepName === 'Category' && !vertical) || applying ? 0.5 : 1,
              }}
            >
              {applying ? 'Setting up…' : 'Continue'} <ArrowRight size={14} />
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
        {step < steps.length - 1 && (
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
