'use client'

import { useEffect, useRef, type CSSProperties } from 'react'
import {
  ArrowRight, BookOpen, Columns3, FileText, DollarSign, GitBranch, Layers, Zap,
  Crosshair, Map, Bell, Play, Star, Check, Users, HardHat, Wrench,
} from 'lucide-react'

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
      ['#pipeline .lp-split > div:first-child', null],
      ['#pipeline .lp-panel', null],
      ['.lp-proof-grid', '.lp-stat'],
      ['.lp-strip-row', 'span'],
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
            <a href="#pipeline">Pipeline</a>
            <a href="#how">How it works</a>
            <a href="#pricing">Pricing</a>
          </div>
          <div className="lp-nav-actions">
            <a href="/login" className="lp-btn lp-btn-ghost">Sign in</a>
            <a href="/login" className="lp-btn lp-btn-accent">Get started</a>
          </div>
        </div>
      </nav>

      {/* ── Hero ── */}
      <header className="lp-hero">
        <div className="lp-container">
          <span className="lp-badge" data-hero style={{ '--i': 0 } as CSSProperties}>
            <Zap size={14} /> Automated lead scoring for service businesses
          </span>
          <h1 data-hero style={{ '--i': 1 } as CSSProperties}>
            Built on data,<br /><em>powered by people.</em>
          </h1>
          <p className="lp-hero-sub" data-hero style={{ '--i': 2 } as CSSProperties}>
            Axon gives small businesses enterprise-grade intelligence — without the complexity. Surface
            the insights that matter, understand your customers, and make confident decisions every day.
          </p>
          <div className="lp-hero-ctas" data-hero style={{ '--i': 3 } as CSSProperties}>
            <a className="lp-btn lp-btn-accent lp-btn-lg" href="/login">
              Open your dashboard <ArrowRight size={16} />
            </a>
            <a className="lp-btn lp-btn-outline lp-btn-lg" href="#how">
              <Play size={16} /> See how it works
            </a>
          </div>
          <div className="lp-hero-trust" data-hero style={{ '--i': 4 } as CSSProperties}>
            <div className="lp-avatars">
              <span style={{ background: 'var(--color-moss)' }}>HC</span>
              <span style={{ background: 'var(--color-ocean)' }}>PS</span>
              <span style={{ background: 'var(--color-plum)' }}>SL</span>
              <span style={{ background: 'var(--color-accent)' }}>RF</span>
            </div>
            <span>Used by HVAC, pool, solar, and flooring contractors</span>
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

      {/* ── Industry strip ── */}
      <div className="lp-strip">
        <div className="lp-container">
          <p className="lp-strip-label">Built for service contractors across verticals</p>
          <div className="lp-strip-row">
            <span>HVAC Services</span><span>Pool &amp; Spa</span><span>Solar Install</span>
            <span>Epoxy Flooring</span><span>Roofing Co.</span><span>Pest Control</span>
          </div>
        </div>
      </div>

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

      {/* ── Stats ── */}
      <section className="lp-proof">
        <div className="lp-container">
          <div className="lp-proof-grid">
            <div className="lp-stat"><span className="lp-stat-v accent">50k+</span><span className="lp-stat-l">Property leads<br />scored per territory</span></div>
            <div className="lp-stat"><span className="lp-stat-v">5 hrs</span><span className="lp-stat-l">Saved per week vs.<br />manual spreadsheets</span></div>
            <div className="lp-stat"><span className="lp-stat-v accent">3.8×</span><span className="lp-stat-l">Higher contact rate<br />on grade-A leads</span></div>
            <div className="lp-stat"><span className="lp-stat-v">1 app</span><span className="lp-stat-l">Replacing CRM, tasks,<br />expenses &amp; invoicing</span></div>
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

      {/* ── CTA ── */}
      <section className="lp-cta">
        <div className="lp-container">
          <h2>Predictive insights,<br /><em>personal connections</em></h2>
          <div className="lp-cta-actions">
            <a className="lp-btn lp-btn-accent lp-btn-lg" href="/login">Open your dashboard</a>
            <a className="lp-btn lp-btn-ghost lp-btn-lg" href="#how" style={{ color: 'rgba(255,255,255,0.85)' }}>See how it works</a>
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
                <li><a href="#pipeline">Pipeline</a></li>
                <li><a href="#how">How it works</a></li>
              </ul>
            </div>
            <div>
              <div className="lp-footer-ct">Platform</div>
              <ul className="lp-footer-links">
                <li><a href="/login">Lead scoring</a></li>
                <li><a href="/login">Kanban pipeline</a></li>
                <li><a href="/login">Invoicing &amp; AR</a></li>
                <li><a href="/login">Bookkeeping</a></li>
              </ul>
            </div>
            <div>
              <div className="lp-footer-ct">Account</div>
              <ul className="lp-footer-links">
                <li><a href="/login">Sign in</a></li>
                <li><a href="#">Privacy</a></li>
                <li><a href="#">Terms</a></li>
              </ul>
            </div>
          </div>
          <div className="lp-footer-bottom">
            <span>© 2026 Axon, a Castillo &amp; Co LLC company.</span>
            <span>Predictive insights, personal connections</span>
          </div>
        </div>
      </footer>
    </div>
  )
}
