import './landing.css'
import Link from 'next/link'
import ThemeSwitcher from '@/components/ThemeSwitcher'
import {
  Zap, ArrowRight, PlayCircle,
  LayoutDashboard, Columns2, CheckSquare, Receipt, FileText, BookOpen, Settings,
  Layers, Star, GitBranch, TrendingUp, TrendingDown,
  Bell, Target, Map,
} from 'lucide-react'

export const metadata = {
  title: 'Axon — Built on data, focused on people',
  description: 'Axon turns public property data into ranked leads and runs your entire service-business back-office in one place.',
}

export default function LandingPage() {
  return (
    <div className="lp-root" data-theme="cobalt" data-bg="dark-gray" data-texture="none">
      <ThemeSwitcher />
      {/* ── Navigation ── */}
      <nav className="lp-nav">
        <div className="lp-container lp-nav-inner">
          <a href="#" className="lp-nav-logo">
            <svg width="28" height="28" viewBox="0 0 32 32" fill="none" aria-hidden="true">
              <mask id="axon-mark-nav">
                <rect width="32" height="32" fill="white" />
                <rect x="2" y="14.5" width="28" height="3" rx="1.5" fill="black" />
                <rect x="14.5" y="2" width="3" height="28" rx="1.5" fill="black" />
              </mask>
              <polygon points="16,5 27,16 16,27 5,16" fill="var(--color-accent)" mask="url(#axon-mark-nav)" />
              <circle cx="16" cy="16" r="1.5" fill="var(--color-ink-900)" />
            </svg>
            <span className="lp-nav-wordmark">Axon</span>
          </a>
          <ul className="lp-nav-links">
            <li><a href="#features">Features</a></li>
            <li><a href="#pipeline">Pipeline</a></li>
            <li><a href="#how">How it works</a></li>
            <li><a href="#pricing">Pricing</a></li>
          </ul>
          <div className="lp-nav-actions">
            <Link href="/login" className="lp-btn lp-btn-ghost">Sign in</Link>
            <Link href="/login" className="lp-btn lp-btn-dark">Get started</Link>
          </div>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section className="lp-hero">
        <div className="lp-container">
          <div className="lp-hero-badge">
            <Zap size={12} />
            Automated lead scoring for service businesses
          </div>
          <h1 className="lp-hero-heading">
            Built on data,<br /><em>powered by people.</em>
          </h1>
          <p className="lp-hero-sub">
            Axon gives small businesses enterprise-grade intelligence — without the complexity. Surface the insights that matter, understand your customers, and make confident decisions every day.
          </p>
          <div className="lp-hero-ctas">
            <Link href="/login" className="lp-btn lp-btn-accent lp-btn-lg">
              Open your dashboard
              <ArrowRight size={16} />
            </Link>
            <a href="#how" className="lp-btn lp-btn-outline lp-btn-lg">
              <PlayCircle size={16} />
              See how it works
            </a>
          </div>
          <div className="lp-hero-trust">
            <div className="lp-hero-trust-avatars">
              <span style={{ background: 'var(--color-moss)' }}>HC</span>
              <span style={{ background: 'var(--color-ocean-d)' }}>PS</span>
              <span style={{ background: 'var(--color-plum)' }}>SL</span>
              <span style={{ background: 'var(--color-accent)' }}>RF</span>
            </div>
            <span>Used by HVAC, pool, solar, and flooring contractors</span>
          </div>

          {/* Dashboard mockup */}
          <div className="lp-hero-visual">
            <div className="lp-dashboard-frame">
              <div className="lp-dash-titlebar">
                <div className="lp-dash-dot lp-dash-dot-r" />
                <div className="lp-dash-dot lp-dash-dot-y" />
                <div className="lp-dash-dot lp-dash-dot-g" />
              </div>
              <div className="lp-dash-body">
                <div className="lp-dash-sidebar">
                  <div className="lp-dash-sidebar-logo">
                    <svg width="18" height="18" viewBox="0 0 32 32" fill="none" aria-hidden="true">
                      <mask id="axon-mark-mockup">
                        <rect width="32" height="32" fill="white" />
                        <rect x="2" y="14.5" width="28" height="3" rx="1.5" fill="black" />
                        <rect x="14.5" y="2" width="3" height="28" rx="1.5" fill="black" />
                      </mask>
                      <polygon points="16,5 27,16 16,27 5,16" fill="var(--color-accent)" mask="url(#axon-mark-mockup)" />
                      <circle cx="16" cy="16" r="1.5" fill="#f6f7f9" />
                    </svg>
                    <span>Axon</span>
                  </div>
                  <div className="lp-dash-nav-item active">
                    <LayoutDashboard size={14} />
                    Overview
                  </div>
                  <div className="lp-dash-nav-item">
                    <Star size={14} />
                    Leads
                  </div>
                  <div className="lp-dash-nav-item">
                    <Columns2 size={14} />
                    Pipeline
                  </div>
                  <div className="lp-dash-nav-item">
                    <CheckSquare size={14} />
                    Tasks
                  </div>
                  <div className="lp-dash-nav-item">
                    <Receipt size={14} />
                    Expenses
                  </div>
                  <div className="lp-dash-nav-item">
                    <FileText size={14} />
                    Invoices
                  </div>
                  <div className="lp-dash-nav-item">
                    <BookOpen size={14} />
                    Bookkeeping
                  </div>
                  <div className="lp-dash-nav-item">
                    <Settings size={14} />
                    Scheduler
                  </div>
                </div>
                <div className="lp-dash-main">
                  <div className="lp-dash-topbar">
                    <span className="lp-dash-title">Good morning, Pete</span>
                    <span className="lp-dash-date">Jun 1, 2026</span>
                  </div>
                  <div className="lp-dash-metrics">
                    <div className="lp-dash-metric">
                      <div className="lp-dash-metric-label">Pipeline Value</div>
                      <div className="lp-dash-metric-value">$142k</div>
                      <div className="lp-dash-metric-delta">
                        <TrendingUp size={10} />
                        +$18k this week
                      </div>
                    </div>
                    <div className="lp-dash-metric">
                      <div className="lp-dash-metric-label">Scored Leads</div>
                      <div className="lp-dash-metric-value">1,847</div>
                      <div className="lp-dash-metric-delta">
                        <TrendingUp size={10} />
                        +124 this run
                      </div>
                    </div>
                    <div className="lp-dash-metric">
                      <div className="lp-dash-metric-label">Tasks Due Today</div>
                      <div className="lp-dash-metric-value">8</div>
                      <div className="lp-dash-metric-delta neg">
                        <TrendingDown size={10} />
                        3 overdue
                      </div>
                    </div>
                    <div className="lp-dash-metric">
                      <div className="lp-dash-metric-label">Outstanding AR</div>
                      <div className="lp-dash-metric-value">$9,450</div>
                      <div className="lp-dash-metric-delta">
                        <TrendingUp size={10} />
                        2 invoices
                      </div>
                    </div>
                  </div>
                  <div className="lp-dash-charts">
                    <div className="lp-dash-chart-card">
                      <div className="lp-dash-chart-label">Lead scores — this run</div>
                      <div className="lp-chart-bars">
                        <div className="lp-chart-bar" style={{ height: '30%' }} />
                        <div className="lp-chart-bar" style={{ height: '55%' }} />
                        <div className="lp-chart-bar" style={{ height: '70%' }} />
                        <div className="lp-chart-bar" style={{ height: '65%' }} />
                        <div className="lp-chart-bar" style={{ height: '80%' }} />
                        <div className="lp-chart-bar" style={{ height: '72%' }} />
                        <div className="lp-chart-bar hi" style={{ height: '90%' }} />
                      </div>
                    </div>
                    <div className="lp-dash-chart-card">
                      <div className="lp-dash-chart-label">Pipeline by stage</div>
                      <div style={{ height: 80, display: 'flex', alignItems: 'center' }}>
                        <svg viewBox="0 0 200 64" fill="none" style={{ width: '100%', height: '100%' }}>
                          <path
                            d="M0 52 C20 48 40 40 70 32 C100 24 130 18 155 14 C175 11 190 9 200 7"
                            stroke="var(--color-accent)" strokeWidth="2" fill="none"
                          />
                          <path
                            d="M0 52 C20 48 40 40 70 32 C100 24 130 18 155 14 C175 11 190 9 200 7 L200 64 L0 64Z"
                            fill="var(--color-accent-50)"
                          />
                        </svg>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Industry strip ── */}
      <div className="lp-logos-section">
        <div className="lp-container">
          <p className="lp-logos-label">Built for service contractors across verticals</p>
          <div className="lp-logos-row">
            <span className="lp-logo-item">HVAC Services</span>
            <span className="lp-logo-item">Pool &amp; Spa</span>
            <span className="lp-logo-item">Solar Install</span>
            <span className="lp-logo-item">Epoxy Flooring</span>
            <span className="lp-logo-item">Roofing Co.</span>
            <span className="lp-logo-item">Pest Control</span>
            <span className="lp-logo-item">& More</span>
          </div>
        </div>
      </div>

      {/* ── Features ── */}
      <section className="lp-features-section" id="features">
        <div className="lp-container">
          <div className="lp-section-eyebrow">
            <Layers size={12} />
            What Axon does
          </div>
          <h2 className="lp-section-heading">
            Everything a big enterprise has —<br />built for the way you actually work
          </h2>
          <p className="lp-section-sub">
            Axon connects your data sources, learns your business patterns, and delivers intelligence that feels less like a report and more like advice from a trusted partner.
          </p>
          <div className="lp-features-grid">
            <div className="lp-feature-card">
              <div className="lp-feature-icon accent"><Star size={20} /></div>
              <h3 className="lp-feature-name">Lead scoring engine</h3>
              <p className="lp-feature-desc">
                Axon pulls public property records for your target ZIP codes and scores every address by
                opportunity size, condition signals, and vertical fit. Know who to call before you dial.
              </p>
            </div>
            <div className="lp-feature-card">
              <div className="lp-feature-icon ocean"><Columns2 size={20} /></div>
              <h3 className="lp-feature-name">Visual pipeline</h3>
              <p className="lp-feature-desc">
                Drag leads through your stages — New, Contacted, Quoted, Won — on a live Kanban board.
                See your total pipeline value update in real time as deals move forward.
              </p>
            </div>
            <div className="lp-feature-card">
              <div className="lp-feature-icon moss"><CheckSquare size={20} /></div>
              <h3 className="lp-feature-name">Task management</h3>
              <p className="lp-feature-desc">
                Create tasks linked to specific properties and leads, set priorities from low to urgent,
                and get overdue alerts. Your follow-up list and your CRM, finally in sync.
              </p>
            </div>
            <div className="lp-feature-card">
              <div className="lp-feature-icon gold"><Receipt size={20} /></div>
              <h3 className="lp-feature-name">Expense tracker</h3>
              <p className="lp-feature-desc">
                Log every business expense by category — fuel, materials, subcontractors, and more. Flag
                tax-deductible items and export a clean CSV for your accountant any time.
              </p>
            </div>
            <div className="lp-feature-card">
              <div className="lp-feature-icon plum"><FileText size={20} /></div>
              <h3 className="lp-feature-name">Invoicing &amp; accounts receivable</h3>
              <p className="lp-feature-desc">
                Build invoices with line items, record partial payments, and pull an AR aging report with
                one click. Know exactly who owes you, and how long they&apos;ve owed it.
              </p>
            </div>
            <div className="lp-feature-card">
              <div className="lp-feature-icon rose"><BookOpen size={20} /></div>
              <h3 className="lp-feature-name">Bookkeeping &amp; P&amp;L</h3>
              <p className="lp-feature-desc">
                See your monthly profit and loss and per-property job costing — revenue versus expenses
                and margin per job. No separate accounting app needed.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── Split: Pipeline ── */}
      <section className="lp-section" id="pipeline">
        <div className="lp-container">
          <div className="lp-split-section">
            <div>
              <div className="lp-section-eyebrow">
                <Star size={12} />
                Lead intelligence
              </div>
              <h2 className="lp-section-heading">Your data knows what&#39;s coming -<br/> now so do you</h2>
              <p className="lp-section-sub">
                Axons intelligence layer reads patterns across your business and flags what needs your attention — not what already happened.
              </p>
              <div className="lp-split-points">
                <div className="lp-split-point">
                  <div className="lp-split-point-icon"><Bell size={16} /></div>
                  <div className="lp-split-point-text">
                    <strong>Automated scoring runs</strong>
                    <span>
                      Schedule your pipeline to score leads by ZIP code and vertical on any cadence.
                      Wake up to a fresh ranked list with no manual work.
                    </span>
                  </div>
                </div>
                <div className="lp-split-point">
                  <div className="lp-split-point-icon"><GitBranch size={16} /></div>
                  <div className="lp-split-point-text">
                    <strong>Grade-based prioritization</strong>
                    <span>
                      Each lead gets an A–F grade based on score percentile. Filter by grade so your
                      team focuses exclusively on the highest-potential properties.
                    </span>
                  </div>
                </div>
                <div className="lp-split-point">
                  <div className="lp-split-point-icon"><Target size={16} /></div>
                  <div className="lp-split-point-text">
                    <strong>One-click pipeline entry</strong>
                    <span>
                      Promote any scored lead into your Kanban pipeline, assign a task, and add notes —
                      all from the same lead detail drawer.
                    </span>
                  </div>
                </div>
              </div>
            </div>
            <div>
              <div className="lp-insight-panel">
                <div className="lp-insight-header">
                  <span className="lp-insight-title">Top scored leads — 77007</span>
                  <span className="lp-insight-badge">124 new</span>
                </div>
                <div className="lp-insight-list">
                  <div className="lp-insight-item">
                    <div className="lp-insight-item-dot" style={{ background: 'var(--color-accent)' }} />
                    <div style={{ flex: 1 }}>
                      <div className="lp-insight-item-headline">1842 Westheimer Rd — Grade A</div>
                      <div className="lp-insight-item-detail">
                        3,400 sq ft single-family, built 1987. High signal for HVAC replacement based on
                        age and lot characteristics.
                      </div>
                    </div>
                    <div className="lp-insight-item-metric">Score 94</div>
                  </div>
                  <div className="lp-insight-item">
                    <div className="lp-insight-item-dot" style={{ background: 'var(--color-moss)' }} />
                    <div style={{ flex: 1 }}>
                      <div className="lp-insight-item-headline">504 River Oaks Blvd — Quote sent</div>
                      <div className="lp-insight-item-detail">
                        In pipeline · contacted last Tuesday · quote for epoxy garage at $6,200. Follow-up
                        task due tomorrow.
                      </div>
                    </div>
                    <div className="lp-insight-item-metric">$6.2k</div>
                  </div>
                  <div className="lp-insight-item">
                    <div className="lp-insight-item-dot" style={{ background: 'var(--color-ocean-d)' }} />
                    <div style={{ flex: 1 }}>
                      <div className="lp-insight-item-headline">3 leads in &ldquo;Contacted&rdquo; past 14 days</div>
                      <div className="lp-insight-item-detail">
                        No activity in two weeks on these accounts. Add a follow-up task to keep them
                        from going cold.
                      </div>
                    </div>
                    <div className="lp-insight-item-metric">$21k</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Stats proof ── */}
      <section className="lp-proof-section">
        <div className="lp-container">
          <div className="lp-proof-inner">
            <div className="lp-proof-stat">
              <span className="lp-proof-stat-value lp-proof-stat-accent">50k+</span>
              <span className="lp-proof-stat-label">Property leads<br />scored per territory</span>
            </div>
            <div className="lp-proof-stat">
              <span className="lp-proof-stat-value">5 hrs</span>
              <span className="lp-proof-stat-label">Saved per week vs.<br />manual spreadsheets</span>
            </div>
            <div className="lp-proof-stat">
              <span className="lp-proof-stat-value lp-proof-stat-accent">3.8×</span>
              <span className="lp-proof-stat-label">Higher contact rate<br />on grade-A leads</span>
            </div>
            <div className="lp-proof-stat">
              <span className="lp-proof-stat-value">1 app</span>
              <span className="lp-proof-stat-label">Replacing CRM, tasks,<br />expenses &amp; invoicing</span>
            </div>
          </div>
        </div>
      </section>

      {/* ── How it works ── */}
      <section className="lp-section" id="how">
        <div className="lp-container">
          <div style={{ textAlign: 'center', maxWidth: 540, margin: '0 auto' }}>
            <div className="lp-section-eyebrow" style={{ justifyContent: 'center' }}>
              <Map size={12} />
              How it works
            </div>
            <h2 className="lp-section-heading">From territory to closed job — in one workflow</h2>
            <p className="lp-section-sub" style={{ margin: '0 auto' }}>
              No data team. No complex setup. Point Axon at your ZIP codes and vertical, and it handles
              the rest — from lead discovery to invoicing.
            </p>
          </div>
          <div className="lp-how-steps">
            <div className="lp-how-step">
              <div className="lp-how-step-number active">01</div>
              <h3 className="lp-how-step-title">Set your territory</h3>
              <p className="lp-how-step-desc">
                Choose your ZIP codes and service vertical. Schedule scoring runs daily, weekly, or on
                demand — Axon pulls fresh property data automatically.
              </p>
            </div>
            <div className="lp-how-step">
              <div className="lp-how-step-number">02</div>
              <h3 className="lp-how-step-title">Work your ranked leads</h3>
              <p className="lp-how-step-desc">
                Open the lead table sorted by score, filter to grade-A properties, and add the best ones
                to your Kanban pipeline. Assign tasks, take notes, and track every touchpoint.
              </p>
            </div>
            <div className="lp-how-step">
              <div className="lp-how-step-number">03</div>
              <h3 className="lp-how-step-title">Invoice, track, and close the books</h3>
              <p className="lp-how-step-desc">
                When you win a job, create an invoice in seconds. Log your expenses, monitor your AR,
                and check your P&amp;L — Axon ties the whole job together so nothing falls through the cracks.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── CTA band ── */}
      <section className="lp-cta-section">
        <div className="lp-container">
          <h2 className="lp-cta-heading">
            Predictive insights, <br /><em>personal connections</em>
          </h2>
          <div className="lp-cta-actions">
            <Link href="/login" className="lp-btn lp-btn-paper lp-btn-lg">Open your dashboard</Link>
            <a href="#how" className="lp-btn lp-btn-ghost lp-btn-lg" style={{ color: 'rgba(255,255,255,0.7)' }}>
              See how it works
            </a>
          </div>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="lp-footer">
        <div className="lp-container">
          <div className="lp-footer-inner">
            <div>
              <span className="lp-footer-wordmark">
                <svg width="20" height="20" viewBox="0 0 32 32" fill="none" aria-hidden="true">
                  <mask id="axon-mark-footer">
                    <rect width="32" height="32" fill="white" />
                    <rect x="2" y="14.5" width="28" height="3" rx="1.5" fill="black" />
                    <rect x="14.5" y="2" width="3" height="28" rx="1.5" fill="black" />
                  </mask>
                  <polygon points="16,5 27,16 16,27 5,16" fill="var(--color-accent)" mask="url(#axon-mark-footer)" />
                  <circle cx="16" cy="16" r="1.5" fill="#f6f7f9" />
                </svg>
                Axon
              </span>
              <p className="lp-footer-tagline">Built on data, powered by people.</p>
            </div>
            <div>
              <div className="lp-footer-col-title">Product</div>
              <ul className="lp-footer-links">
                <li><a href="#features">Features</a></li>
                <li><a href="#pipeline">Pipeline</a></li>
                <li><a href="#how">How it works</a></li>
              </ul>
            </div>
            <div>
              <div className="lp-footer-col-title">Platform</div>
              <ul className="lp-footer-links">
                <li><Link href="/login">Lead scoring</Link></li>
                <li><Link href="/login">Kanban pipeline</Link></li>
                <li><Link href="/login">Invoicing &amp; AR</Link></li>
                <li><Link href="/login">Bookkeeping</Link></li>
              </ul>
            </div>
            <div>
              <div className="lp-footer-col-title">Account</div>
              <ul className="lp-footer-links">
                <li><Link href="/login">Sign in</Link></li>
                <li><a href="#">Privacy</a></li>
                <li><a href="#">Terms</a></li>
              </ul>
            </div>
          </div>
          <div className="lp-footer-bottom">
            <span>&copy; 2026 Axon Intelligence, Inc. All rights reserved.</span>
            <span>Predictive insights, personal connections</span>
          </div>
        </div>
      </footer>
    </div>
  )
}
