'use client'

import { useEffect, useRef, useState, type CSSProperties } from 'react'
import {
  ArrowRight, Columns3, FileText, DollarSign, GitBranch, Layers, Download,
  Map, Bell, Play, Star, Check, Users,
  Database, HelpCircle, X, Mail, MapPin, CloudLightning,
  MessageSquare, PenLine, Zap,
} from 'lucide-react'
import { ZipSampleWidget, WAITLIST_MAILTO } from '@/components/ZipSampleWidget'
import { LandingPhoto } from '@/components/LandingPhoto'
import { ProspectCaptureForm } from '@/components/ProspectCaptureForm'
import { TESTIMONIALS, SHOW_TESTIMONIALS } from '@/lib/testimonials'
import { getPublicStats } from '@/lib/api'

// ── Comparison data (Axon vs. the shared-lead marketplaces) ──
// The criticism belongs to the shared-lead business model, not to any one
// company: cell copy states each platform's publicly documented pay-per-lead
// model, and nothing here asserts a price or a contractor outcome.
const VS_RIVALS = [
  { name: 'Angi', sub: 'Shared-lead marketplace' },
  { name: 'HomeAdvisor', sub: 'Shared-lead marketplace' },
  { name: 'Thumbtack', sub: 'Shared-lead marketplace' },
]

const VS_ROWS: Array<{ label: string; rivals: [string, string, string]; axon: string }> = [
  {
    label: 'Who else gets the same name',
    rivals: ['Shared with up to 4 pros', 'Shared with up to 4 pros', 'Any pro who pays can chase it'],
    axon: 'Nobody — your list is built for your account alone',
  },
  {
    label: 'How you pay',
    rivals: ['Per lead, win or lose', 'Per lead, plus an annual fee', 'Per lead, at their price'],
    axon: 'One flat monthly price, however many properties you work',
  },
  {
    label: 'Where the list comes from',
    rivals: ['Whoever fills out the national form', 'Same funnel, different logo', 'National app traffic'],
    axon: 'Harris County records, permits & storm data',
  },
  {
    label: 'Local knowledge',
    rivals: ['One playbook for every market', 'One playbook for every market', 'One playbook for every market'],
    axon: 'Scored street by street in your ZIP codes',
  },
  {
    label: 'Why it’s on your list',
    rivals: ['No explanation', 'No explanation', 'No explanation'],
    axon: 'Every score shows its signals',
  },
  {
    label: 'Who owns the customer',
    rivals: ['The platform', 'The platform', 'The platform'],
    axon: 'You do — export everything, anytime',
  },
]

const AxonMark = ({ size = 28, maskId }: { size?: number; maskId: string }) => (
  <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true">
    <mask id={maskId}>
      <rect width="32" height="32" fill="white" />
      <rect x="2" y="14.5" width="28" height="3" rx="1.5" fill="black" />
      <rect x="14.5" y="2" width="3" height="28" rx="1.5" fill="black" />
    </mask>
    <polygon points="16,5 27,16 16,27 5,16" fill="var(--color-accent)" mask={`url(#${maskId})`} />
    <circle cx="16" cy="16" r="1.5" fill="#f6f7f9" />
  </svg>
)

// Below this, a platform-wide count reads as thin rather than as proof — the
// chip stays hidden until the number has real weight.
const MIN_PROOF_COUNT = 500

export default function LandingContent() {
  const rootRef = useRef<HTMLDivElement>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const posterRef = useRef<HTMLDivElement>(null)
  const [scoredCount, setScoredCount] = useState<number | null>(null)

  // Live-ish proof chip for the ZIP demo — real count, cached daily server-side.
  useEffect(() => {
    getPublicStats()
      .then(s => setScoredCount(s.properties_scored))
      .catch(() => {})
  }, [])

  // ── Video poster: only hide it once the clip actually starts playing. ──
  useEffect(() => {
    const v = videoRef.current
    const poster = posterRef.current
    if (!v || !poster) return
    const reveal = () => { if (v.readyState >= 3 && !v.paused) poster.classList.add('hidden') }
    v.addEventListener('playing', reveal)
    v.addEventListener('loadeddata', reveal)
    return () => {
      v.removeEventListener('playing', reveal)
      v.removeEventListener('loadeddata', reveal)
    }
  }, [])

  // ── Scroll/entrance animations (ported from the marketing kit). ──
  useEffect(() => {
    const root = rootRef.current
    if (!root) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return // CSS leaves everything visible

    root.classList.add('lp-anim')
    const cleanups: Array<() => void> = []

    // Auto-tag reveal targets + their staggered children.
    const groups: Array<[string, string | null]> = [
      ['#features .lp-eyebrow', null], ['#features .lp-h2', null], ['#features .lp-section-sub', null],
      ['.lp-features', '.lp-feature'],
      ['#compare .lp-eyebrow', null], ['#compare .lp-h2', null], ['#compare .lp-section-sub', null],
      ['.lp-vs-wrap', '.lp-vs-row'], ['.lp-vs-foot', null],
      ['#pipeline .lp-split > div:first-child', null],
      ['#pipeline .lp-panel', null],
      ['.lp-proof-grid', '.lp-stat'],
      ['#pricing .lp-eyebrow', null], ['#pricing .lp-h2', null], ['#pricing .lp-section-sub', null],
      ['.lp-pricing-grid', '.lp-price-card'],
      ['#faq .lp-eyebrow', null], ['#faq .lp-h2', null],
      ['.lp-faq-list', 'details'],
      ['.lp-cta h2', null], ['.lp-cta-actions', null], ['.lp-cta-note', null],
      ['.lp-footer-inner', '> div'],
    ]
    groups.forEach(([sel, childSel]) => {
      root.querySelectorAll<HTMLElement>(sel).forEach((el) => {
        el.setAttribute('data-reveal', '')
        if (childSel) {
          const kids = childSel.startsWith('>')
            ? [...el.children]
            : el.querySelectorAll(childSel)
          ;[...kids].forEach((k, i) => {
            k.setAttribute('data-stagger', '')
            ;(k as HTMLElement).style.setProperty('--i', String(i))
          })
        }
      })
    })

    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) { e.target.classList.add('is-in'); io.unobserve(e.target) }
      })
    }, { threshold: 0.15, rootMargin: '0px 0px -8% 0px' })
    root.querySelectorAll('[data-reveal]').forEach((el) => io.observe(el))
    cleanups.push(() => io.disconnect())

    // Count-up helper (parses the leading number on an element, keeps its suffix).
    const tickCount = (el: HTMLElement, dur = 1100) => {
      const raw = (el.textContent || '').trim()
      const m = raw.match(/^([\d.]+)(.*)$/)
      if (!m) return
      const target = parseFloat(m[1]); const suffix = m[2]
      const decimals = (m[1].split('.')[1] || '').length
      const t0 = performance.now()
      const tick = (now: number) => {
        const p = Math.min(1, (now - t0) / dur)
        const eased = 1 - Math.pow(1 - p, 3) // easeOutCubic
        el.textContent = (target * eased).toFixed(decimals) + suffix
        if (p < 1) requestAnimationFrame(tick)
        else el.textContent = m[1] + suffix
      }
      requestAnimationFrame(tick)
    }

    // Count-up on the proof stats.
    const cio = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (!e.isIntersecting) return
        cio.unobserve(e.target)
        tickCount(e.target as HTMLElement)
      })
    }, { threshold: 0.5 })
    root.querySelectorAll('.lp-stat-v').forEach((el) => cio.observe(el))
    cleanups.push(() => cio.disconnect())

    // Feature-card demos: play their mini animation once in view, replay on hover.
    const demoCards = [...root.querySelectorAll<HTMLElement>('.lp-feature')]
    const playDemo = (card: HTMLElement) => {
      card.classList.add('is-demo-in')
      card.querySelectorAll<HTMLElement>('.lp-demo-count').forEach((el) => tickCount(el, 900))
    }
    const dio = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) { playDemo(e.target as HTMLElement); dio.unobserve(e.target) }
      })
    }, { threshold: 0.35 })
    demoCards.forEach((card) => dio.observe(card))
    cleanups.push(() => dio.disconnect())

    const onDemoReplay: Array<() => void> = []
    demoCards.forEach((card) => {
      const replay = () => {
        card.classList.remove('is-demo-in')
        void card.offsetWidth // force reflow so the transition restarts from 0
        playDemo(card)
      }
      card.addEventListener('mouseenter', replay)
      onDemoReplay.push(() => card.removeEventListener('mouseenter', replay))
    })
    cleanups.push(() => onDemoReplay.forEach((fn) => fn()))

    // Traveling process visual — activate the step straddling the viewport
    // center, and glide the visual frame down so it docks at the bottom of
    // that step (CSS transitions the move; see .lp-pcol-visual in landing.css).
    const pSteps = [...root.querySelectorAll<HTMLElement>('.lp-pstep')]
    const pVis = [...root.querySelectorAll<HTMLElement>('.lp-pvis')]
    const pDock = root.querySelector<HTMLElement>('.lp-pcol-visual')
    if (pSteps.length && pVis.length && pDock) {
      let current = -1
      let lastY = -1
      const dock = () => {
        // Bottom-align the frame with the active step, relative to the grid.
        const step = pSteps[Math.max(0, current)]
        const y = Math.max(0, step.offsetTop + step.offsetHeight - pDock.offsetHeight - 24)
        if (Math.abs(y - lastY) >= 1) { lastY = y; pDock.style.setProperty('--pvis-y', `${y}px`) }
      }
      const setActive = (idx: number) => {
        if (idx === current) return
        current = idx
        pSteps.forEach((s, i) => s.classList.toggle('is-active', i === idx))
        pVis.forEach((vEl, i) => vEl.classList.toggle('is-active', i === idx))
      }
      const pick = () => {
        const cy = window.innerHeight / 2
        let idx = pSteps.findIndex((s) => { const b = s.getBoundingClientRect(); return b.top <= cy && b.bottom >= cy })
        if (idx < 0) idx = pSteps.reduce((best, s, i) => {
          const b = s.getBoundingClientRect(); const d = Math.abs((b.top + b.bottom) / 2 - cy)
          return d < best.d ? { d, i } : best
        }, { d: Infinity, i: 0 }).i
        setActive(idx)
        dock() // re-measure every pass so font/image load and resizes self-correct
      }
      let ticking = false
      const onScroll = () => { if (!ticking) { ticking = true; requestAnimationFrame(() => { pick(); ticking = false }) } }
      window.addEventListener('scroll', onScroll, { passive: true })
      window.addEventListener('resize', onScroll, { passive: true })
      pick()
      // Enable the glide transition only after the first dock, so the frame
      // doesn't animate from the top of the grid on initial paint.
      const dockRaf = requestAnimationFrame(() => pDock.classList.add('is-docked'))
      cleanups.push(() => {
        cancelAnimationFrame(dockRaf)
        window.removeEventListener('scroll', onScroll)
        window.removeEventListener('resize', onScroll)
      })
    }

    // Hero entrance — fire on next frame so transitions run.
    const raf = requestAnimationFrame(() => requestAnimationFrame(() => root.classList.add('lp-ready')))
    cleanups.push(() => cancelAnimationFrame(raf))

    return () => cleanups.forEach((fn) => fn())
  }, [])

  return (
    <div ref={rootRef}>
      {/* ── Nav ── */}
      <nav className="lp-nav">
        <div className="lp-container lp-nav-inner">
          <a href="#" className="lp-nav-logo">
            <AxonMark maskId="axon-mark-nav" />
            <span className="lp-nav-wordmark">Axon</span>
          </a>
          <div className="lp-nav-links">
            <a href="#features">Features</a>
            <a href="#how">How It Works</a>
            <a href="#pricing">Pricing</a>
            <a href="#faq">FAQ</a>
            <a href="/preview">Live Demo</a>
          </div>
          <div className="lp-nav-actions">
            <a href="/login" className="lp-btn lp-btn-ghost">Sign In</a>
            <a href="/signup" className="lp-btn lp-btn-accent">Start Free</a>
          </div>
        </div>
      </nav>

      {/* ── Hero ── */}
      <header className="lp-hero">
        <div className="lp-container">
          <div className="lp-eyebrow" data-hero style={{ '--i': 0 } as CSSProperties}>
            <MapPin size={12} /> Harris County, Texas
          </div>
          <h1 data-hero style={{ '--i': 1 } as CSSProperties}>
            Fewer calls. <em>Better jobs.</em>
          </h1>
          <p className="lp-hero-sub" data-hero style={{ '--i': 2 } as CSSProperties}>
            Territory intelligence for Harris County contractors: every property in your service
            area, scored and graded A&ndash;D from appraisal, permit, equity, and storm records.
            Call the ones worth your time. Skip the ones that burn gas.
          </p>

          {/* The hero IS the demo. The ZIP widget was below the fold for a year;
              a visitor now sees their own street ranked before they read a claim.
              The id stays on this wrapper so every existing #zip-sample link
              (closing CTA, old inbound links) still lands on the form. */}
          <div className="lp-hero-demo" id="zip-sample" data-hero style={{ '--i': 3 } as CSSProperties}>
            <ZipSampleWidget />
          </div>

          <p className="lp-hero-terms" data-hero style={{ '--i': 4 } as CSSProperties}>
            <Check size={14} aria-hidden="true" />
            14 days free &middot; no credit card &middot; cancel anytime
            <span>Previewing a ZIP needs no email and no account.</span>
          </p>

          {/* ── Proof, above the fold: a real count, sources anyone can check,
                 and the person who built it. No testimonials until they're real. ── */}
          <div className="lp-hero-proof" data-hero style={{ '--i': 5 } as CSSProperties}>
            <div className="lp-hero-evidence">
            {scoredCount != null && scoredCount >= MIN_PROOF_COUNT && (
              <p className="lp-zip-proof-chip">
                <Database size={13} />
                <span><b>{scoredCount.toLocaleString()}</b> Harris County properties scored so far</span>
              </p>
            )}
            <p className="lp-hero-sources">
              Built from public records you can check yourself:{' '}
              <a href="https://hcad.org" target="_blank" rel="noopener noreferrer">Harris County Appraisal District</a>,{' '}
              <a href="https://www.ncei.noaa.gov/access/monitoring/storm-events/" target="_blank" rel="noopener noreferrer">NOAA storm events</a>,{' '}
              <a href="https://data.census.gov" target="_blank" rel="noopener noreferrer">US Census</a>, and city building permits.{' '}
              <a href="/hcad-data" className="lp-hero-sources-more">How HCAD data works <ArrowRight size={12} /></a>
            </p>
            </div>
            {/* TODO(pete): edit this bio in your own words — it is the one place
                on the page where a stranger meets a person instead of a claim. */}
            <div className="lp-founder">
              <LandingPhoto kind="founder" alt="Pete Castillo, who built Axon" className="lp-founder-photo" sizes="72px" />
              <p>
                <b>Built by Pete Castillo</b>{' — '}a data analyst in Houston. The same public
                records that appraise your customers&apos; homes can tell you which doors are worth
                knocking on. Axon is that, for one contractor at a time.{' '}
                <a href="mailto:admin@axonhtx.com">Ask me anything about the data</a>.
              </p>
            </div>
          </div>

          {/* ── Social proof band — hidden for now via SHOW_TESTIMONIALS; the
                 markup stays in place. Turn the flag on (and add real quotes to
                 lib/testimonials.ts — never fabricate) to bring it back. ── */}
          {SHOW_TESTIMONIALS && TESTIMONIALS.length > 0 && (
            <div className="lp-proof-band" data-hero style={{ '--i': 5 } as CSSProperties}>
              {TESTIMONIALS.slice(0, 3).map(t => (
                <figure key={t.name} className="lp-quote">
                  <blockquote>&ldquo;{t.quote}&rdquo;</blockquote>
                  <figcaption>{t.name} · {t.trade}, {t.city}</figcaption>
                </figure>
              ))}
            </div>
          )}

          {/* ── Video header ── */}
          <div className="lp-video-wrap">
            <div className="lp-video-chrome">
              <span className="lp-dot" style={{ background: '#E26A6A' }} />
              <span className="lp-dot" style={{ background: '#E2B06A' }} />
              <span className="lp-dot" style={{ background: '#6AE28B' }} />
            </div>
            <div className="lp-video-stage">
              {/* preload="metadata" + no autoplay: the 5.6 MB promo clip no
                  longer competes with hero text/CSS for bandwidth on first
                  paint (mobile LCP). The poster overlay's play button starts
                  it on demand. */}
              <video ref={videoRef} controls muted loop playsInline preload="metadata">
                <source src="/axon-promo.mp4" type="video/mp4" />
              </video>
              <div className="lp-video-poster" ref={posterRef}>
                <button
                  type="button"
                  className="lp-play"
                  aria-label="Play product demo"
                  onClick={() => videoRef.current?.play().catch(() => {})}
                >
                  <Play size={30} color="var(--text-on-accent)" fill="var(--text-on-accent)" style={{ marginLeft: 4 }} />
                </button>
                <div className="lp-video-caption">See Axon in action</div>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* ── Name the model, not the company: Axon vs. shared-lead marketplaces ── */}
      <section className="lp-section" id="compare" style={{ paddingTop: 72, paddingBottom: 72 }}>
        <div className="lp-container">
          <div className="lp-eyebrow"><Users size={12} /> The shared-lead model</div>
          <h2 className="lp-h2">One homeowner. Five contractors.<br />Everyone pays.</h2>
          <p className="lp-section-sub">
            The shared-lead model sells the same inquiry to several contractors at once. You pay
            whether the homeowner answers or not, then race everyone else to the phone. Axon works
            differently: it builds a ranked list from Harris County property data for one flat
            monthly price.
          </p>
          <div className="lp-vs-shell">
          <div className="lp-vs-wrap">
            <div className="lp-vs" role="table" aria-label="How Axon compares with shared-lead marketplaces">
              <div className="lp-vs-row lp-vs-head" role="row">
                <div className="lp-vs-cell" role="columnheader">
                  <span className="lp-vs-dim">How Axon compares</span>
                </div>
                {VS_RIVALS.map((r) => (
                  <div className="lp-vs-cell" role="columnheader" key={r.name}>
                    <b>{r.name}</b>
                    <span>{r.sub}</span>
                  </div>
                ))}
                <div className="lp-vs-cell" role="columnheader">
                  <span className="lp-vs-flag">The local one</span>
                  <b className="lp-vs-brand"><AxonMark size={18} maskId="axon-mark-vs" /> Axon</b>
                  <span>Your ranked territory list</span>
                </div>
              </div>
              {VS_ROWS.map((row) => (
                <div className="lp-vs-row" role="row" key={row.label}>
                  <div className="lp-vs-cell lp-vs-rowlabel" role="rowheader">
                    <strong>{row.label}</strong>
                  </div>
                  {row.rivals.map((cell, i) => (
                    <div className="lp-vs-cell" role="cell" key={VS_RIVALS[i].name}>
                      <span className="lp-vs-mark lp-vs-no"><X size={12} /></span>
                      <span>{cell}</span>
                    </div>
                  ))}
                  <div className="lp-vs-cell" role="cell">
                    <span className="lp-vs-mark lp-vs-yes"><Check size={12} /></span>
                    <span>{row.axon}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
          </div>
          <p className="lp-section-sub" style={{ marginTop: 32 }}>
            <b>The problem isn&apos;t that you called too slowly. The same name went to several
            contractors.</b> Shared leads turn every inquiry into a two-minute race. Axon gives
            you a ranked territory list you can work deliberately — starting with the properties
            that show the strongest signals.
          </p>
          <p className="lp-vs-foot">
            Marketplace practices summarized from each platform&apos;s publicly documented
            pay-per-lead model; details vary by market, trade, and plan. Angi, HomeAdvisor, and
            Thumbtack are trademarks of their respective owners — no affiliation or endorsement
            implied.
          </p>
        </div>
      </section>

      {/* ── Split: pipeline ── */}
      <section className="lp-section" id="pipeline" style={{ paddingTop: 24 }}>
        <div className="lp-container">
          <div className="lp-split">
            <div>
              <div className="lp-eyebrow"><Star size={12} /> Territory intelligence</div>
              <h2 className="lp-h2">Local data, read street by street —<br />and ranked for your trade</h2>
              <p className="lp-section-sub">
                Axon reads the public record across your ZIP codes and puts the properties in
                order, so the first call of the day is the one with the strongest signals behind it.
              </p>
              <div className="lp-points">
                <div className="lp-point">
                  <div className="lp-point-ic"><Bell size={16} /></div>
                  <div>
                    <strong>Scoring runs on your schedule</strong>
                    <span>Score by ZIP and trade on demand or on a cadence. Wake up to a fresh ranked list with no manual work.</span>
                  </div>
                </div>
                <div className="lp-point">
                  <div className="lp-point-ic"><GitBranch size={16} /></div>
                  <div>
                    <strong>Grade-based prioritization</strong>
                    <span>Every property carries a 0–100 score and an A–D grade. Filter by grade so your crew starts where the signals are strongest.</span>
                  </div>
                </div>
                <div className="lp-point">
                  <div className="lp-point-ic"><CloudLightning size={16} /></div>
                  <div>
                    <strong>Storm Mode</strong>
                    <span>The morning after hail hits, Axon emails you the affected homes in your territory, already ranked — before the out-of-town crews finish loading their trucks.</span>
                  </div>
                </div>
                <div className="lp-point">
                  <div className="lp-point-ic"><Map size={16} /></div>
                  <div>
                    <strong>See your territory on a map</strong>
                    <span>Every scored property plotted with grade heatmaps — plan a route through a neighborhood of A&apos;s instead of driving to scattered addresses.</span>
                  </div>
                </div>
              </div>
            </div>
            <div>
              <div className="lp-panel">
                <div className="lp-panel-head">
                  <h4>Top scored properties — 77007</h4>
                  <span style={{ fontSize: 10, fontWeight: 700, padding: '3px 9px', borderRadius: 'var(--radius-pill)', background: 'var(--color-accent-100)', color: 'var(--color-accent-300)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>124 new</span>
                </div>
                <div className="lp-panel-list">
                  <div className="lp-panel-item">
                    <span className="lp-panel-dot" style={{ background: 'var(--color-accent)' }} />
                    <div>
                      <h5>1842 Westheimer Rd — Grade A</h5>
                      <p>3,400 sq ft single-family, built 1987. High signal for HVAC replacement.</p>
                    </div>
                    <span className="lp-panel-metric" style={{ color: 'var(--color-accent-300)' }}>94</span>
                  </div>
                  <div className="lp-panel-item">
                    <span className="lp-panel-dot" style={{ background: 'var(--color-moss)' }} />
                    <div>
                      <h5>504 River Oaks Blvd — Quote sent</h5>
                      <p>In pipeline · quote for epoxy garage at $6,200. Follow-up due tomorrow.</p>
                    </div>
                    <span className="lp-panel-metric" style={{ color: 'var(--color-moss)' }}>$6.2k</span>
                  </div>
                  <div className="lp-panel-item">
                    <span className="lp-panel-dot" style={{ background: 'var(--color-ocean)' }} />
                    <div>
                      <h5>3 leads cold past 14 days</h5>
                      <p>No activity in two weeks. Add a follow-up task to keep them warm.</p>
                    </div>
                    <span className="lp-panel-metric" style={{ color: 'var(--color-ink-700)' }}>$21k</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Where the data comes from (transparency band) ── */}
      <section className="lp-proof">
        <div className="lp-container">
          <p className="lp-proof-label"><Database size={13} /> Where the data comes from</p>
          <div className="lp-proof-grid">
            <div className="lp-stat"><span className="lp-stat-v accent" style={{ fontSize: 22 }}>County records</span><span className="lp-stat-l">Harris County appraisal data:<br />year built, value, owner, pool, garage</span></div>
            <div className="lp-stat"><span className="lp-stat-v" style={{ fontSize: 22 }}>US Census</span><span className="lp-stat-l">Neighborhood income &amp;<br />demographic context by ZIP</span></div>
            <div className="lp-stat"><span className="lp-stat-v accent" style={{ fontSize: 22 }}>NOAA storms</span><span className="lp-stat-l">Hail, wind &amp; tornado reports<br />matched to each address</span></div>
            <div className="lp-stat"><span className="lp-stat-v" style={{ fontSize: 22 }}>Building permits</span><span className="lp-stat-l">Renovation history that signals<br />budget and project timing</span></div>
          </div>
          <p className="lp-proof-foot">
            No black box: open any property in Axon and the &ldquo;Why this score&rdquo; panel lists
            the exact signals behind its grade.
          </p>
        </div>
      </section>

      {/* ── Features ── */}
      <section className="lp-section" id="features" style={{ paddingTop: 24 }}>
        <div className="lp-container">
          <div className="lp-eyebrow"><Layers size={12} /> After the list</div>
          <h2 className="lp-h2">The ranked territory list —<br />and everything to run the job after</h2>
          <p className="lp-section-sub">
            The ranked list is the part nobody else sells. Everything else — pipeline stages,
            texting, quotes, invoicing — is included so that when the list points you at a job,
            nothing drops between the first call and getting paid.
          </p>
          <div className="lp-features">
            <div className="lp-feature">
              <div className="lp-feature-ic" style={{ background: 'var(--color-info-bg)', color: 'var(--color-ocean)' }}><Columns3 size={18} /></div>
              <h3>Visual pipeline</h3>
              <p>Drag leads through your stages — New, Contacted, Quoted, Won — on a live board, with linked follow-up tasks and overdue alerts so nothing slips.</p>
              <div className="lp-feature-demo lp-demo-pipeline" aria-hidden="true">
                <span className="lp-demo-pipe-chip">Lead</span>
                <div className="lp-demo-pipe-track">
                  <span className="lp-demo-pipe-col">New</span>
                  <span className="lp-demo-pipe-col">Contacted</span>
                  <span className="lp-demo-pipe-col">Quoted</span>
                  <span className="lp-demo-pipe-col">Won</span>
                </div>
              </div>
            </div>
            <div className="lp-feature">
              <div className="lp-feature-ic" style={{ background: 'var(--color-accent-100)', color: 'var(--color-accent-300)' }}><MessageSquare size={18} /></div>
              <h3>Two-way texting</h3>
              <p>Text customers right from the lead — with reusable templates that fill in the name, address, and quote amount for you. Every reply lands on the lead&apos;s timeline.</p>
              <div className="lp-feature-demo lp-demo-sms" aria-hidden="true">
                <div className="lp-demo-bubble lp-demo-bubble-out">Hi Maria — your quote for the roof repair is ready: $6,200.</div>
                <div className="lp-demo-bubble lp-demo-bubble-in">Looks good, when can you start?</div>
              </div>
            </div>
            <div className="lp-feature">
              <div className="lp-feature-ic" style={{ background: 'var(--color-info-bg)', color: 'var(--color-ocean)' }}><PenLine size={18} /></div>
              <h3>Quotes homeowners can accept online</h3>
              <p>Build a quote in minutes and send a public link — the homeowner reviews and accepts from their phone, then it converts to an invoice in one click.</p>
              <div className="lp-feature-demo lp-demo-invoice" aria-hidden="true">
                <span className="lp-demo-inv-stamp">Accepted</span>
                <div className="lp-demo-inv-line"><span>Quote #218 — epoxy garage</span><span>$6,200</span></div>
                <div className="lp-demo-inv-line"><span>Sent as a link · no login needed</span><span /></div>
                <div className="lp-demo-inv-total"><span>Accepted by customer</span><span>2:15 PM</span></div>
              </div>
            </div>
            <div className="lp-feature">
              <div className="lp-feature-ic" style={{ background: 'var(--color-plum-soft)', color: 'var(--color-plum)' }}><FileText size={18} /></div>
              <h3>Invoicing &amp; payments</h3>
              <p>Build invoices with line items, take payments, and pull an AR aging report with one click — with job costing and expenses tracked against every job.</p>
              <div className="lp-feature-demo lp-demo-invoice" aria-hidden="true">
                <span className="lp-demo-inv-stamp">Paid</span>
                <div className="lp-demo-inv-line"><span>HVAC replacement</span><span>$18,400</span></div>
                <div className="lp-demo-inv-line"><span>Labor — 2 crew</span><span>$3,600</span></div>
                <div className="lp-demo-inv-total"><span>Total due</span><span>$22,000</span></div>
              </div>
            </div>
            <div className="lp-feature">
              <div className="lp-feature-ic" style={{ background: 'var(--color-gold-soft)', color: 'var(--color-gold)' }}><Zap size={18} /></div>
              <h3>Automatic follow-ups &amp; appointments</h3>
              <p>Set rules once — quote sent, no reply in 3 days, stage changed — and Axon creates the follow-up task or text for you. Book appointments on the same record.</p>
              <div className="lp-feature-demo lp-demo-tasks" aria-hidden="true">
                <div className="lp-demo-task">
                  <span className="lp-demo-check"><Check size={12} /></span>
                  <span className="lp-demo-task-label">Quote sent → follow-up task in 3 days</span>
                </div>
                <div className="lp-demo-task">
                  <span className="lp-demo-check"><Check size={12} /></span>
                  <span className="lp-demo-task-label">Job won → book install appointment</span>
                </div>
              </div>
            </div>
            <div className="lp-feature lp-feature-photo">
              <LandingPhoto kind="doorstep" alt="An Axon customer at a Harris County front door" sizes="(max-width: 860px) 100vw, 33vw" />
              <div className="lp-feature-photo-cap">
                <strong>The list gets you to the door.</strong>
                <span>The rest is still you.</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Powered by people ── */}
      <section className="lp-people">
        <div className="lp-container lp-people-grid">
          <div data-reveal>
            <div className="lp-eyebrow"><Users size={12} /> Powered by people</div>
            <h2>Data points the way.<br /><em>People close the job.</em></h2>
            <p className="lp-people-sub">
              Axon does the analysis so your team can do what software can&apos;t — show up, build trust,
              and win the work. The intelligence runs quietly in the background; the relationships stay yours.
            </p>
          </div>
          {/* A day the data built — the route card tells the people story in the
              product's own language: the map points the way, the crew closes. */}
          <div className="lp-people-visual" data-reveal>
            <LandingPhoto kind="crew" alt="A Houston crew on a job in their territory" className="lp-people-photo" />
            <div className="lp-route-card">
              <div className="lp-route-head">
                <span className="t-eyebrow">Tuesday&apos;s route · 77007</span>
                <span className="lp-route-badge">3 stops · all grade A</span>
              </div>
              <div className="lp-route-map" aria-hidden="true">
                <svg className="lp-route-svg" viewBox="0 0 100 70" preserveAspectRatio="none">
                  <path className="lp-route-trail" d="M 13 50 C 22 42, 33 40, 46 32 C 59 24, 70 20, 83 14" />
                </svg>
                <span className="lp-route-dot" style={{ left: '24%', top: '26%' }} />
                <span className="lp-route-dot" style={{ left: '70%', top: '63%' }} />
                <span className="lp-route-dot" style={{ left: '34%', top: '86%' }} />
                <span className="lp-route-dot" style={{ left: '88%', top: '74%' }} />
                <span className="lp-route-dot" style={{ left: '55%', top: '12%' }} />
                <span className="lp-route-pin is-stop1" />
                <span className="lp-route-pin is-stop2" />
                <span className="lp-route-pin is-stop3 is-end" />
                <span className="lp-route-chip is-stop1"><b>9:00</b> Inspect roof</span>
                <span className="lp-route-chip is-stop2"><b>11:30</b> Quote signed</span>
                <span className="lp-route-chip is-stop3 is-won"><b>2:15</b> Job won <Check size={11} /></span>
              </div>
              <div className="lp-route-foot">
                <div className="lp-route-crew" aria-hidden="true"><span>MR</span><span>DT</span><span>+2</span></div>
                <span className="lp-route-crew-label">Marcus&apos;s crew — on doors by 9, booked by 3</span>
                <b className="lp-route-total">$23,200 booked</b>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── How it works — scroll-pinned process ── */}
      <section className="lp-process" id="how">
        <div className="lp-container">
          <div className="lp-process-head" data-reveal>
            <div className="lp-eyebrow" style={{ justifyContent: 'center' }}><Map size={12} /> How it works</div>
            <h2 className="lp-h2">From territory to closed job — in one workflow</h2>
            <p className="lp-section-sub" style={{ margin: '0 auto' }}>
              Choose your ZIP codes and trade. Axon ranks the properties, shows why each one
              scored, and keeps the work together from first call to paid invoice.
            </p>
          </div>
          <div className="lp-process-grid">
            <div className="lp-pcol-steps">
              <div className="lp-pstep" data-step="0">
                <div className="lp-pstep-n"><b>01</b><span>Set your territory</span></div>
                <h3>Tell Axon where to look</h3>
                <p>Choose your ZIP codes and trade. Run property scoring on demand or on a schedule. Axon reads the available records and ranks the properties for you.</p>
              </div>
              <div className="lp-pstep" data-step="1">
                <div className="lp-pstep-n"><b>02</b><span>Work your ranked list</span></div>
                <h3>Call the A&apos;s first</h3>
                <p>Start with the highest-ranked properties and open any score to see why it moved up the list. Add the properties you want to work to your pipeline stages.</p>
              </div>
              <div className="lp-pstep" data-step="2">
                <div className="lp-pstep-n"><b>03</b><span>Invoice &amp; close the books</span></div>
                <h3>Win it, bill it, book it</h3>
                <p>When a job moves forward, build the quote, send the invoice, log the expenses, and keep the job margin current without leaving Axon.</p>
              </div>
            </div>
            <div className="lp-pcol-visual">
              <div className="lp-pvis-frame">
                {/* 01 territory map */}
                <div className="lp-pvis is-active" data-vis="0">
                  <div className="lp-pvis-head"><span className="t-eyebrow">Territory · 77007</span></div>
                  <div className="lp-mini-map">
                    <span className="lp-pin" style={{ left: '22%', top: '30%' }} />
                    <span className="lp-pin" style={{ left: '58%', top: '24%' }} />
                    <span className="lp-pin" style={{ left: '40%', top: '54%' }} />
                    <span className="lp-pin" style={{ left: '71%', top: '62%' }} />
                    <span className="lp-pin" style={{ left: '30%', top: '74%' }} />
                    <span className="lp-pin" style={{ left: '82%', top: '40%', background: 'var(--color-gold)', boxShadow: '0 0 0 4px rgba(240,183,38,0.25)' }} />
                  </div>
                </div>
                {/* 02 ranked leads */}
                <div className="lp-pvis" data-vis="1">
                  <div className="lp-pvis-head"><span className="t-eyebrow">Ranked properties</span></div>
                  <div className="lp-mini-row"><span className="grade" style={{ background: 'var(--color-success-bg)', color: 'var(--color-success)' }}>A</span><span className="addr">1842 Westheimer Rd</span><span className="val">$14k</span></div>
                  <div className="lp-mini-row"><span className="grade" style={{ background: 'var(--color-success-bg)', color: 'var(--color-success)' }}>A</span><span className="addr">504 River Oaks Blvd</span><span className="val">$6.2k</span></div>
                  <div className="lp-mini-row"><span className="grade" style={{ background: 'var(--color-info-bg)', color: 'var(--color-info)' }}>B</span><span className="addr">3300 Kirby Dr</span><span className="val">$9.8k</span></div>
                  <div className="lp-mini-row"><span className="grade" style={{ background: 'var(--color-info-bg)', color: 'var(--color-info)' }}>B</span><span className="addr">77 Tanglewood Ln</span><span className="val">$12k</span></div>
                </div>
                {/* 03 invoice */}
                <div className="lp-pvis" data-vis="2">
                  <div className="lp-pvis-head"><span className="t-eyebrow">Invoice · #1042</span></div>
                  <div className="lp-mini-inv">
                    <div className="lp-mini-line"><span>HVAC system replacement</span><span>$18,400</span></div>
                    <div className="lp-mini-line"><span>Permit &amp; disposal</span><span>$1,200</span></div>
                    <div className="lp-mini-line"><span>Labor — 2 crew · 3 days</span><span>$3,600</span></div>
                    <div className="lp-mini-total"><span className="t-eyebrow" style={{ margin: 0 }}>Total due</span><b>$23,200</b></div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Pricing ── */}
      <section className="lp-section" id="pricing" style={{ paddingTop: 72 }}>
        <div className="lp-container">
          <div className="lp-eyebrow"><DollarSign size={12} /> Pricing</div>
          <h2 className="lp-h2">The advertised price is the real price</h2>
          <p className="lp-section-sub">
            Flat monthly plans, and every plan starts with 14 days free — no credit card
            required.
          </p>
          {/* Anchor against the model the ICP already pays into, before they read a tier. */}
          <div className="lp-price-anchor">
            <span className="lp-price-anchor-old">Shared leads: <b>per name</b>, win or lose</span>
            <ArrowRight size={14} aria-hidden="true" />
            <span className="lp-price-anchor-new">Axon: <b>one flat monthly price</b>, your whole team included</span>
          </div>
          <div className="lp-pricing-grid">
            <div className="lp-price-card">
              <h3>Starter</h3>
              <div className="lp-price"><span className="lp-price-n">$49</span><span className="lp-price-per">/mo</span></div>
              <p className="lp-price-blurb">Get organized — and see your first scored properties every month.</p>
              <ul>
                <li><Check size={15} /> 25 scored properties from your ZIPs each month</li>
                <li><Check size={15} /> Leads, pipeline stages &amp; tasks</li>
                <li><Check size={15} /> Notes, history &amp; saved segments</li>
                <li><Check size={15} /> Two-way texting &amp; templates</li>
                <li><Check size={15} /> Full CSV export — your data is yours</li>
              </ul>
              <a className="lp-btn lp-btn-outline" href="/signup">Start Free</a>
            </div>
            <div className="lp-price-card">
              <h3>Growth</h3>
              <div className="lp-price"><span className="lp-price-n">$129</span><span className="lp-price-per">/mo</span></div>
              <p className="lp-price-blurb">Run the back office: from quote to paid, in the same tab.</p>
              <ul>
                <li><Check size={15} /> 100 scored properties each month</li>
                <li><Check size={15} /> Everything in Starter</li>
                <li><Check size={15} /> Quotes with public accept links</li>
                <li><Check size={15} /> Invoicing, online payments &amp; AR aging</li>
                <li><Check size={15} /> Job costing, receipts &amp; expenses</li>
                <li><Check size={15} /> Automatic follow-ups &amp; appointments</li>
              </ul>
              <a className="lp-btn lp-btn-outline" href="/signup">Start Free</a>
            </div>
            <div className="lp-price-card lp-price-featured">
              <span className="lp-price-flag">Most contractors pick this</span>
              <h3>Pro</h3>
              <div className="lp-price"><span className="lp-price-n">$249</span><span className="lp-price-per">/mo</span></div>
              <p className="lp-price-blurb">Your ranked territory list — with the signals behind every score.</p>
              <ul>
                <li><Check size={15} /> Unlimited property scoring across your territory</li>
                <li><Check size={15} /> Everything in Growth</li>
                <li><Check size={15} /> &ldquo;Why this score&rdquo; on every property</li>
                <li><Check size={15} /> Storm &amp; permit timing signals</li>
                <li><Check size={15} /> Property map, territories &amp; heatmaps</li>
                <li><Check size={15} /> CSV lead import</li>
                <li><Check size={15} /> Call tracking number &amp; call log</li>
              </ul>
              <a className="lp-btn lp-btn-accent" href="/signup">Start Free</a>
            </div>
          </div>
          {/* ── item 8: the anchor with the arithmetic in it. Angi publishes no
                 price list, so the figure is stated as the reported range it is,
                 and the comparison is arithmetic the reader can redo. ── */}
          <div className="lp-price-math">
            <div className="lp-price-math-side">
              <span className="lp-price-math-label">Shared leads</span>
              <span className="lp-price-math-eq"><b>$80</b> &times; 3 leads = <b>$240</b></span>
              <span className="lp-price-math-note">
                Three names, each shared with up to four other contractors. Nothing left over
                at the end of the month.
              </span>
            </div>
            <div className="lp-price-math-vs">vs</div>
            <div className="lp-price-math-side is-axon">
              <span className="lp-price-math-label">Axon Pro</span>
              <span className="lp-price-math-eq"><b>$249</b> / month</span>
              <span className="lp-price-math-note">
                Every property in your territory, scored, with the signals behind each grade —
                yours to work for the whole month.
              </span>
            </div>
          </div>
          <p className="lp-pricing-foot">
            Angi does not publish a price list; contractors report paying roughly $15&ndash;$85 per
            shared lead, with roofing and HVAC install leads at the top of that range. The math
            above uses $80. Check it against your own last invoice from{' '}
            <a href="https://www.angi.com/" target="_blank" rel="noopener noreferrer">angi.com</a>{' '}
            — if your cost per lead is lower, run the same three lines again with your number.
          </p>
          <div className="lp-keep-row">
            <span><Check size={14} /> Month to month, cancel anytime</span>
            <span><Download size={14} /> Full CSV export, not just on the way out</span>
            <span><DollarSign size={14} /> One flat price, never per name</span>
          </div>
        </div>
      </section>

      {/* ── FAQ ── */}
      <section className="lp-section" id="faq" style={{ paddingTop: 24 }}>
        <div className="lp-container">
          <div className="lp-eyebrow"><HelpCircle size={12} /> Questions, answered straight</div>
          <h2 className="lp-h2">Straight answers for skeptical owners</h2>
          <div className="lp-faq-list">
            <details>
              <summary>Where does the property data actually come from?</summary>
              <p>
                Public records: county appraisal rolls (year built, value, owner, pool, garage),
                US Census neighborhood data, NOAA/NWS storm reports, and building permits. Axon
                combines them into a 0–100 score with an A–D grade — and every property shows the
                exact signals behind its score, so you never have to take a number on faith.
              </p>
            </details>
            <details>
              <summary>How fast do I see my first list?</summary>
              <p>
                The ZIP sample above is instant — type a ZIP and a scored list renders in
                seconds. After you sign up, a full territory run (every scored property across
                your ZIP codes and trade) completes the same day, usually within a few hours.
              </p>
            </details>
            <details>
              <summary>How is this different from buying leads?</summary>
              <p>
                A purchased lead is one homeowner who filled out a form — sold to you and several
                competitors at once. An Axon list is every promising property in your service
                area, ranked, with owner and contact details where available. It is built for your
                account alone, and you pay a flat monthly price, not per name. Nobody on that list
                has raised a hand yet; the score tells you where to start, and the call is still
                yours to make.
              </p>
            </details>
            <details>
              <summary>Is there a contract?</summary>
              <p>
                Axon is month to month. Cancel anytime. The advertised price is the price, and
                your data leaves with you.
              </p>
            </details>
            <details>
              <summary>Do I have to rip out QuickBooks or my field-service app?</summary>
              <p>
                No. Axon owns the front of your business — where the next customer comes from and
                how the deal gets worked. Keep QuickBooks for accounting or Jobber for dispatch as
                long as you like: Axon imports and exports clean CSVs, so nothing is trapped.
              </p>
            </details>
            <details>
              <summary>Is contacting these homeowners legal?</summary>
              <p>
                The data comes from public records, and lots of businesses market from the same
                sources. Outreach rules still apply to you as the caller — telemarketing laws like
                the federal Do-Not-Call registry for cold calls, and consent requirements for
                texting. Axon shows where every contact came from so you can make honest, informed
                outreach decisions. See Axon&apos;s <a href="/privacy">Privacy Policy</a> for details.
              </p>
            </details>
            <details>
              <summary>What happens to my data if I cancel?</summary>
              <p>
                It leaves with you. Every list, contact, note, invoice, and expense exports to CSV
                at any time — no exit fees, no data hostage-taking.
              </p>
            </details>
          </div>
        </div>
      </section>

      {/* ── CTA ── */}
      <section className="lp-cta">
        <div className="lp-container">
          <h2>Stop paying for shared leads.<br /><em>Start working your own territory.</em></h2>
          <p className="lp-cta-note" style={{ margin: '0 auto 28px' }}>
            Preview a Harris County ZIP free. See the ranked properties and the signals behind
            every score — no email required.
          </p>
          <div className="lp-cta-actions">
            <a className="lp-btn lp-btn-accent lp-btn-lg" href="#zip-sample">Preview Your ZIP</a>
            <a className="lp-btn lp-btn-ghost lp-btn-lg" href="/preview" style={{ color: 'rgba(255,255,255,0.85)' }}>Try the Live Demo</a>
          </div>
          <p className="lp-cta-note">
            Axon currently serves Harris County, Texas — with local appraisal, permit, and storm
            data built into every score. Outside Harris County?{' '}
            <a href={WAITLIST_MAILTO}>Join the waitlist</a> to bring Axon to your area.
          </p>
          <div style={{ marginTop: 36, paddingTop: 28, borderTop: '1px solid rgba(255,255,255,0.15)' }}>
            <p style={{ color: 'rgba(255,255,255,0.85)', fontWeight: 600, margin: '0 0 12px' }}>
              Not ready to start? Get a personal walkthrough of Axon.
            </p>
            <ProspectCaptureForm source="landing" dark />
          </div>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="lp-footer">
        <div className="lp-container">
          <div className="lp-footer-inner">
            <div>
              <span className="lp-footer-wordmark"><AxonMark size={20} maskId="axon-mark-footer" /> Axon</span>
              <p className="lp-footer-tag">Built on data, powered by people.</p>
            </div>
            <div>
              <div className="lp-footer-ct">Product</div>
              <ul className="lp-footer-links">
                <li><a href="#features">Features</a></li>
                <li><a href="#how">How It Works</a></li>
                <li><a href="#pricing">Pricing</a></li>
                <li><a href="/preview">Live Demo</a></li>
                <li><a href="/hcad-data">HCAD Data, Explained</a></li>
              </ul>
            </div>
            <div>
              <div className="lp-footer-ct">Account</div>
              <ul className="lp-footer-links">
                <li><a href="/signup">Start Free</a></li>
                <li><a href="/login">Sign In</a></li>
                <li><a href="mailto:admin@axonhtx.com"><Mail size={13} style={{ verticalAlign: '-2px', marginRight: 5 }} />Contact Axon</a></li>
              </ul>
            </div>
            <div>
              <div className="lp-footer-ct">Legal</div>
              <ul className="lp-footer-links">
                <li><a href="/privacy">Privacy Policy</a></li>
                <li><a href="/terms">Terms of Service</a></li>
              </ul>
            </div>
          </div>
          <div className="lp-footer-bottom">
            <span>© 2026 Axon, a Castillo &amp; Co LLC company.</span>
            <span>Built on data, powered by people</span>
          </div>
        </div>
      </footer>
    </div>
  )
}
