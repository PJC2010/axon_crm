'use client'

import { useEffect, useRef, type CSSProperties } from 'react'
import {
  ArrowRight, BookOpen, Columns3, FileText, DollarSign, GitBranch, Layers, Zap,
  Crosshair, Map, Bell, Play, Star, Check, Users, HardHat, Wrench,
  Database, HelpCircle, X, Mail, MapPin, CloudLightning,
} from 'lucide-react'
import { ZipSampleWidget } from '@/components/ZipSampleWidget'

// ── Competitor comparison data (Axon vs. the national lead marketplaces) ──
// Cell copy states each platform's publicly documented pay-per-lead model;
// keep claims generic-but-true and let the repetition make the point.
const VS_RIVALS = [
  { name: 'Angi', sub: 'National marketplace' },
  { name: 'HomeAdvisor', sub: 'National marketplace' },
  { name: 'Thumbtack', sub: 'National marketplace' },
]

const VS_ROWS: Array<{ label: string; rivals: [string, string, string]; axon: string }> = [
  {
    label: 'Who else gets the lead',
    rivals: ['Shared with up to 4 pros', 'Shared with up to 4 pros', 'Any pro who pays can chase it'],
    axon: 'Nobody — built from your territory, for you alone',
  },
  {
    label: 'How you pay',
    rivals: ['Per lead, win or lose', 'Per lead, plus an annual fee', 'Per lead, at their price'],
    axon: 'One flat monthly price, however many leads you work',
  },
  {
    label: 'Where leads come from',
    rivals: ['Whoever fills out the national form', 'Same funnel, different logo', 'National app traffic'],
    axon: 'Your county’s records, permits & storm data',
  },
  {
    label: 'Local knowledge',
    rivals: ['One playbook for every market', 'One playbook for every market', 'One playbook for every market'],
    axon: 'Scored street by street in your ZIP codes',
  },
  {
    label: 'Why you got the lead',
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

export default function LandingContent() {
  const rootRef = useRef<HTMLDivElement>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const posterRef = useRef<HTMLDivElement>(null)

  // ── Video poster: only hide it once a real clip actually starts playing. ──
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
      ['.lp-strip-row', 'span'],
      ['#pricing .lp-eyebrow', null], ['#pricing .lp-h2', null], ['#pricing .lp-section-sub', null],
      ['.lp-pricing-grid', '.lp-price-card'],
      ['#faq .lp-eyebrow', null], ['#faq .lp-h2', null],
      ['.lp-faq-list', 'details'],
      ['.lp-cta h2', null], ['.lp-cta-actions', null],
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

    // Scroll-pinned process — activate the step straddling the viewport center.
    const pSteps = [...root.querySelectorAll<HTMLElement>('.lp-pstep')]
    const pVis = [...root.querySelectorAll<HTMLElement>('.lp-pvis')]
    if (pSteps.length && pVis.length) {
      let current = -1
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
      }
      let ticking = false
      const onScroll = () => { if (!ticking) { ticking = true; requestAnimationFrame(() => { pick(); ticking = false }) } }
      window.addEventListener('scroll', onScroll, { passive: true })
      window.addEventListener('resize', onScroll, { passive: true })
      pick()
      cleanups.push(() => {
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
            <a href="#how">How it works</a>
            <a href="#pricing">Pricing</a>
            <a href="#faq">FAQ</a>
            <a href="/preview">Live demo</a>
          </div>
          <div className="lp-nav-actions">
            <a href="/login" className="lp-btn lp-btn-ghost">Sign in</a>
            <a href="/signup" className="lp-btn lp-btn-accent">Start free</a>
          </div>
        </div>
      </nav>

      {/* ── Hero ── */}
      <header className="lp-hero">
        <div className="lp-container">
          <span className="lp-badge" data-hero style={{ '--i': 0 } as CSSProperties}>
            <Zap size={14} /> Exclusive, scored leads for service businesses
          </span>
          <h1 data-hero style={{ '--i': 1 } as CSSProperties}>
            Know which homeowners in your ZIP need you —<br /><em>before they call anyone.</em>
          </h1>
          <p className="lp-hero-sub" data-hero style={{ '--i': 2 } as CSSProperties}>
            Axon scores every property in your service area using county records, permits, equity,
            and storm data — then hands you a ranked call list with the reason behind every score.
            No shared leads. No contracts.
          </p>
          <div className="lp-hero-ctas" data-hero style={{ '--i': 3 } as CSSProperties}>
            <a className="lp-btn lp-btn-accent lp-btn-lg" href="#zip-sample">
              See your ZIP&apos;s top leads — free <ArrowRight size={16} />
            </a>
            <a className="lp-btn lp-btn-outline lp-btn-lg" href="/preview">
              <Play size={16} /> Try the live demo
            </a>
          </div>
          <div className="lp-hero-trust" data-hero style={{ '--i': 4 } as CSSProperties}>
            <Database size={15} style={{ flexShrink: 0 }} />
            <span>
              Scores built from Harris County appraisal records, US Census data, NOAA storm
              reports, and building permits — and every lead shows its work.
            </span>
          </div>

          {/* ── Video header ── */}
          <div className="lp-video-wrap">
            <div className="lp-video-chrome">
              <span className="lp-dot" style={{ background: '#E26A6A' }} />
              <span className="lp-dot" style={{ background: '#E2B06A' }} />
              <span className="lp-dot" style={{ background: '#6AE28B' }} />
            </div>
            <div className="lp-video-stage">
              <video ref={videoRef} autoPlay muted loop playsInline poster="" preload="auto">
                <source src="/hero-demo.mp4" type="video/mp4" />
              </video>
              <div className="lp-video-poster" ref={posterRef}>
                <button
                  type="button"
                  className="lp-play"
                  aria-label="Play product demo"
                  onClick={() => videoRef.current?.play().catch(() => {})}
                >
                  <Play size={30} color="#fff" style={{ marginLeft: 4 }} />
                </button>
                <div className="lp-video-caption">See Axon in action</div>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* ── ZIP-sample widget: the 60-second personal proof ── */}
      <section className="lp-section" id="zip-sample" style={{ paddingTop: 72, paddingBottom: 64 }}>
        <div className="lp-container">
          <div className="lp-eyebrow"><MapPin size={12} /> Try it on your own turf</div>
          <h2 className="lp-h2">Enter your ZIP. See the list.</h2>
          <p className="lp-section-sub">
            Real properties, real scores, straight from county records — addresses partially
            hidden until you create a free account. No email required to look.
          </p>
          <ZipSampleWidget />
        </div>
      </section>

      {/* ── Industry strip ── */}
      <div className="lp-strip">
        <div className="lp-container">
          <p className="lp-strip-label">Built for service contractors across verticals</p>
          <div className="lp-strip-row">
            <span>HVAC Services</span><span>Pool &amp; Spa</span><span>Solar Install</span>
            <span>Epoxy Flooring</span><span>Roofing Co.</span><span>Pressure Washing</span>
          </div>
        </div>
      </div>

      {/* ── Name the enemy: Axon vs. the national lead marketplaces ── */}
      <section className="lp-section" id="compare" style={{ paddingTop: 72, paddingBottom: 72 }}>
        <div className="lp-container">
          <div className="lp-eyebrow"><Crosshair size={12} /> Axon vs. Angi, HomeAdvisor &amp; Thumbtack</div>
          <h2 className="lp-h2">The same lead, sold to five of you, for $80.<br />Sound familiar?</h2>
          <p className="lp-section-sub">
            Angi, HomeAdvisor, Thumbtack — different logos, same national playbook: one
            homeowner&apos;s form, sold to every contractor in the ZIP at $15–$120 a name, win or
            lose. Axon works the other way: an exclusive list built from your county&apos;s own
            data, for one flat monthly price.
          </p>
          <div className="lp-vs-wrap">
            <div className="lp-vs" role="table" aria-label="Axon compared with Angi, HomeAdvisor, and Thumbtack">
              <div className="lp-vs-row lp-vs-head" role="row">
                <div className="lp-vs-cell" role="columnheader">
                  <span className="lp-vs-dim">What you&apos;re buying</span>
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
                  <span>Your territory&apos;s lead engine</span>
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
          <p className="lp-vs-foot">
            Marketplace practices summarized from each platform&apos;s publicly documented
            pay-per-lead model; details vary by market, trade, and plan. Angi, HomeAdvisor, and
            Thumbtack are trademarks of their respective owners — no affiliation or endorsement
            implied.
          </p>
        </div>
      </section>

      {/* ── Features ── */}
      <section className="lp-section" id="features" style={{ paddingTop: 80 }}>
        <div className="lp-container">
          <div className="lp-eyebrow"><Layers size={12} /> What Axon does</div>
          <h2 className="lp-h2">Everything a big enterprise has —<br />built for the way you actually work</h2>
          <p className="lp-section-sub">
            Axon connects your data sources, learns your business patterns, and delivers intelligence
            that feels less like a report and more like advice from a trusted partner.
          </p>
          <div className="lp-features">
            <div className="lp-feature">
              <div className="lp-feature-ic" style={{ background: 'var(--color-accent-100)', color: 'var(--color-accent-300)' }}><Star size={18} /></div>
              <h3>Lead scoring engine</h3>
              <p>Axon pulls public property records for your target ZIP codes and scores every address by opportunity size, condition signals, and vertical fit.</p>
              <div className="lp-feature-demo lp-demo-score" aria-hidden="true">
                <div className="lp-demo-score-head">
                  <span className="lp-demo-score-addr">1842 Westheimer Rd</span>
                  <span className="lp-demo-score-grade">A</span>
                </div>
                <div className="lp-demo-score-track"><div className="lp-demo-score-fill" /></div>
                <div className="lp-demo-score-foot">
                  <span><b className="lp-demo-count">94</b> score</span>
                  <span>Size · Condition · Fit</span>
                </div>
              </div>
            </div>
            <div className="lp-feature">
              <div className="lp-feature-ic" style={{ background: 'var(--color-info-bg)', color: 'var(--color-ocean)' }}><Columns3 size={18} /></div>
              <h3>Visual pipeline</h3>
              <p>Drag leads through your stages — New, Contacted, Quoted, Won — on a live Kanban board. See pipeline value update in real time.</p>
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
              <div className="lp-feature-ic" style={{ background: 'var(--color-success-bg)', color: 'var(--color-moss)' }}><Check size={18} /></div>
              <h3>Task management</h3>
              <p>Create tasks linked to properties and leads, set priorities, and get overdue alerts. Your follow-up list and CRM, finally in sync.</p>
              <div className="lp-feature-demo lp-demo-tasks" aria-hidden="true">
                <div className="lp-demo-task">
                  <span className="lp-demo-check"><Check size={12} /></span>
                  <span className="lp-demo-task-label">Follow up — 1842 Westheimer</span>
                </div>
                <div className="lp-demo-task">
                  <span className="lp-demo-check"><Check size={12} /></span>
                  <span className="lp-demo-task-label">Send quote — River Oaks Blvd</span>
                </div>
              </div>
            </div>
            <div className="lp-feature">
              <div className="lp-feature-ic" style={{ background: 'var(--color-gold-soft)', color: 'var(--color-gold)' }}><DollarSign size={18} /></div>
              <h3>Expense tracker</h3>
              <p>Log every business expense by category — fuel, materials, subs. Flag tax-deductible items and export a clean CSV for your accountant.</p>
              <div className="lp-feature-demo lp-demo-expense" aria-hidden="true">
                <div className="lp-demo-bars">
                  <span className="lp-demo-bar" />
                  <span className="lp-demo-bar" />
                  <span className="lp-demo-bar" />
                </div>
                <div className="lp-demo-expense-labels">
                  <span>Fuel</span><span>Materials</span><span>Subs</span>
                </div>
              </div>
            </div>
            <div className="lp-feature">
              <div className="lp-feature-ic" style={{ background: 'var(--color-plum-soft)', color: 'var(--color-plum)' }}><FileText size={18} /></div>
              <h3>Invoicing &amp; AR</h3>
              <p>Build invoices with line items, record partial payments, and pull an AR aging report with one click. Know exactly who owes you.</p>
              <div className="lp-feature-demo lp-demo-invoice" aria-hidden="true">
                <span className="lp-demo-inv-stamp">Paid</span>
                <div className="lp-demo-inv-line"><span>HVAC replacement</span><span>$18,400</span></div>
                <div className="lp-demo-inv-line"><span>Labor — 2 crew</span><span>$3,600</span></div>
                <div className="lp-demo-inv-total"><span>Total due</span><span>$22,000</span></div>
              </div>
            </div>
            <div className="lp-feature">
              <div className="lp-feature-ic" style={{ background: 'var(--color-rose-soft)', color: 'var(--color-rose)' }}><BookOpen size={18} /></div>
              <h3>Bookkeeping &amp; P&amp;L</h3>
              <p>See your monthly profit and loss and per-property job costing — revenue versus expenses and margin per job. No separate app needed.</p>
              <div className="lp-feature-demo lp-demo-books" aria-hidden="true">
                <svg className="lp-demo-chart" viewBox="0 0 120 40">
                  <polyline points="2,34 22,28 42,30 62,18 82,20 100,8 118,6" />
                </svg>
                <div className="lp-demo-books-foot"><span>P&amp;L trend</span><span className="lp-demo-books-up">+18%</span></div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Split: pipeline ── */}
      <section className="lp-section" id="pipeline" style={{ paddingTop: 0 }}>
        <div className="lp-container">
          <div className="lp-split">
            <div>
              <div className="lp-eyebrow"><Star size={12} /> Lead intelligence</div>
              <h2 className="lp-h2">Your data knows what&apos;s coming —<br />now so do you</h2>
              <p className="lp-section-sub">
                Axon&apos;s intelligence layer reads patterns across your business and flags what needs
                your attention — not what already happened.
              </p>
              <div className="lp-points">
                <div className="lp-point">
                  <div className="lp-point-ic"><Bell size={16} /></div>
                  <div>
                    <strong>Automated scoring runs</strong>
                    <span>Schedule scoring by ZIP and vertical on any cadence. Wake up to a fresh ranked list with no manual work.</span>
                  </div>
                </div>
                <div className="lp-point">
                  <div className="lp-point-ic"><GitBranch size={16} /></div>
                  <div>
                    <strong>Grade-based prioritization</strong>
                    <span>Each lead gets an A–F grade by score percentile. Filter by grade so your team focuses on the best properties.</span>
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
                  <div className="lp-point-ic"><Crosshair size={16} /></div>
                  <div>
                    <strong>One-click pipeline entry</strong>
                    <span>Promote any scored lead into your Kanban pipeline, assign a task, and add notes — all from one drawer.</span>
                  </div>
                </div>
              </div>
            </div>
            <div>
              <div className="lp-panel">
                <div className="lp-panel-head">
                  <h4>Top scored leads — 77007</h4>
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
            No black boxes: open any lead and the &ldquo;Why this score&rdquo; panel lists the exact
            signals behind its grade.
          </p>
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
          <div className="lp-collage" data-reveal>
            <div className="lp-photo">
              <div className="lp-photo-ph"><HardHat size={26} /><span>Field tech on site</span></div>
              <img src="/people-1.jpg" alt="Field technician on a service call" />
              <div className="lp-photo-tint" />
            </div>
            <div className="lp-photo">
              <div className="lp-photo-ph"><Wrench size={22} /><span>Crew at work</span></div>
              <img src="/people-2.jpg" alt="Service crew at work" />
              <div className="lp-photo-tint" />
            </div>
            <div className="lp-photo">
              <div className="lp-photo-ph"><Users size={22} /><span>Owner &amp; customer</span></div>
              <img src="/people-3.jpg" alt="Business owner with a customer" />
              <div className="lp-photo-tint" />
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
              Point Axon at your ZIP codes and vertical, and it handles the rest — from lead discovery to invoicing.
            </p>
          </div>
          <div className="lp-process-grid">
            <div className="lp-pcol-steps">
              <div className="lp-pstep" data-step="0">
                <div className="lp-pstep-n"><b>01</b><span>Set your territory</span></div>
                <h3>Tell Axon where to look</h3>
                <p>Choose your ZIP codes and service vertical. Schedule scoring runs daily, weekly, or on demand — then let the engine work the public property records for you.</p>
              </div>
              <div className="lp-pstep" data-step="1">
                <div className="lp-pstep-n"><b>02</b><span>Work your ranked leads</span></div>
                <h3>Call the A&apos;s first</h3>
                <p>Open the lead table sorted by score, filter to grade-A, and drop the best straight into your Kanban pipeline. No more guessing which door to knock on.</p>
              </div>
              <div className="lp-pstep" data-step="2">
                <div className="lp-pstep-n"><b>03</b><span>Invoice &amp; close the books</span></div>
                <h3>Win it, bill it, book it</h3>
                <p>Win a job, build an invoice in seconds, log expenses against it, and watch your P&amp;L and per-job margin stay current — all without leaving Axon.</p>
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
                  <div className="lp-pvis-head"><span className="t-eyebrow">Ranked leads</span></div>
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
      <section className="lp-section" id="pricing" style={{ paddingTop: 88 }}>
        <div className="lp-container">
          <div className="lp-eyebrow"><DollarSign size={12} /> Pricing</div>
          <h2 className="lp-h2">The advertised price is the real price</h2>
          <p className="lp-section-sub">
            Flat monthly plans. No contracts, no per-lead fees, no cancellation penalties — cancel
            anytime and your data leaves with you. Every plan starts with 14 days free, no credit
            card required.
          </p>
          <div className="lp-pricing-grid">
            <div className="lp-price-card">
              <h3>Starter</h3>
              <div className="lp-price"><span className="lp-price-n">$49</span><span className="lp-price-per">/mo</span></div>
              <p className="lp-price-blurb">Get organized: every lead, task, and conversation in one place.</p>
              <ul>
                <li><Check size={15} /> Leads, Kanban pipeline &amp; tasks</li>
                <li><Check size={15} /> Notes, history &amp; saved segments</li>
                <li><Check size={15} /> Two-way texting &amp; templates</li>
                <li><Check size={15} /> CSV import &amp; full export</li>
              </ul>
              <a className="lp-btn lp-btn-outline" href="/signup">Start free</a>
            </div>
            <div className="lp-price-card">
              <h3>Growth</h3>
              <div className="lp-price"><span className="lp-price-n">$129</span><span className="lp-price-per">/mo</span></div>
              <p className="lp-price-blurb">Run the back office: from quote to paid, in the same tab.</p>
              <ul>
                <li><Check size={15} /> Everything in Starter</li>
                <li><Check size={15} /> Quotes with public accept links</li>
                <li><Check size={15} /> Invoicing, online payments &amp; AR aging</li>
                <li><Check size={15} /> Bookkeeping, receipts &amp; P&amp;L</li>
                <li><Check size={15} /> Workflow automations &amp; appointments</li>
              </ul>
              <a className="lp-btn lp-btn-outline" href="/signup">Start free</a>
            </div>
            <div className="lp-price-card lp-price-featured">
              <span className="lp-price-flag">Replaces your lead budget</span>
              <h3>Pro</h3>
              <div className="lp-price"><span className="lp-price-n">$249</span><span className="lp-price-per">/mo</span></div>
              <p className="lp-price-blurb">The lead machine: exclusive scored lists for your territory.</p>
              <ul>
                <li><Check size={15} /> Everything in Growth</li>
                <li><Check size={15} /> Scored, graded property lists by ZIP</li>
                <li><Check size={15} /> &ldquo;Why this score&rdquo; on every lead</li>
                <li><Check size={15} /> Storm &amp; permit timing signals</li>
                <li><Check size={15} /> Property map, territories &amp; heatmaps</li>
                <li><Check size={15} /> Marketing insights</li>
              </ul>
              <a className="lp-btn lp-btn-accent" href="/signup">Start free</a>
            </div>
          </div>
          <p className="lp-pricing-foot">
            One extra job pays for a year of Axon — a single $4,800 pool deck or $12,500 HVAC
            change-out covers the Pro plan several times over.
          </p>
        </div>
      </section>

      {/* ── FAQ ── */}
      <section className="lp-section" id="faq" style={{ paddingTop: 24 }}>
        <div className="lp-container">
          <div className="lp-eyebrow"><HelpCircle size={12} /> Questions, answered straight</div>
          <h2 className="lp-h2">What skeptical owners ask us</h2>
          <div className="lp-faq-list">
            <details>
              <summary>Where does the lead data actually come from?</summary>
              <p>
                Public records: county appraisal rolls (year built, value, owner, pool, garage),
                US Census neighborhood data, NOAA/NWS storm reports, and building permits. Axon
                combines them into a 0–100 score with a letter grade — and every lead shows the
                exact signals behind its score, so you never have to take a number on faith.
              </p>
            </details>
            <details>
              <summary>How is this different from buying leads?</summary>
              <p>
                A purchased lead is one homeowner who filled out a form — sold to you and several
                competitors at once. An Axon list is every promising property in your service
                area, ranked, with owner and contact details where available — and it&apos;s
                exclusively yours. You pay a flat monthly price, not per name.
              </p>
            </details>
            <details>
              <summary>Is there a contract?</summary>
              <p>
                No. Month to month, cancel anytime, and the advertised price is the price. We
                built Axon for contractors burned by auto-renewing lead-gen contracts — we&apos;re
                not going to run the same play.
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
                outreach decisions. Details in our <a href="/privacy">Privacy Policy</a>.
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
          <h2>Stop paying for shared leads.<br /><em>Start working your own list.</em></h2>
          <div className="lp-cta-actions">
            <a className="lp-btn lp-btn-accent lp-btn-lg" href="/signup">Start free — no credit card</a>
            <a className="lp-btn lp-btn-ghost lp-btn-lg" href="/preview" style={{ color: 'rgba(255,255,255,0.85)' }}>Try the live demo</a>
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
                <li><a href="#how">How it works</a></li>
                <li><a href="#pricing">Pricing</a></li>
                <li><a href="/preview">Live demo</a></li>
              </ul>
            </div>
            <div>
              <div className="lp-footer-ct">Account</div>
              <ul className="lp-footer-links">
                <li><a href="/signup">Start free</a></li>
                <li><a href="/login">Sign in</a></li>
                <li><a href="mailto:castillop92@gmail.com"><Mail size={13} style={{ verticalAlign: '-2px', marginRight: 5 }} />Contact us</a></li>
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
