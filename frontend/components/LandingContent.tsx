'use client'

import { AnchorButton, Card, Elevation, Navbar, Tag } from '@blueprintjs/core'
import {
  ArrowRight, Book, Cog, ColumnLayout, Dashboard, Document, Dollar, GitBranch,
  Layers, Lightning, Locate, Map, Notifications, Play, Star, Tick, TrendingDown, TrendingUp,
} from '@blueprintjs/icons'

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
  return (
    <>
      {/* ── Navigation ── */}
      <Navbar className="lp-nav">
        <div className="lp-container lp-nav-inner">
          <a href="#" className="lp-nav-logo">
            <AxonMark maskId="axon-mark-nav" />
            <span className="lp-nav-wordmark">Axon</span>
          </a>
          <span className="lp-nav-links">
            <AnchorButton variant="minimal" href="#features" text="Features" />
            <AnchorButton variant="minimal" href="#pipeline" text="Pipeline" />
            <AnchorButton variant="minimal" href="#how" text="How it works" />
            <AnchorButton variant="minimal" href="#pricing" text="Pricing" />
          </span>
          <div className="lp-nav-actions">
            <AnchorButton variant="minimal" href="/login" text="Sign in" />
            <AnchorButton intent="primary" href="/login" text="Get started" />
          </div>
        </div>
      </Navbar>

      {/* ── Hero ── */}
      <section className="lp-hero">
        <div className="lp-container">
          <Tag round large minimal intent="primary" icon={<Lightning />} className="lp-hero-badge">
            Automated lead scoring for service businesses
          </Tag>
          <h1 className="lp-hero-heading">
            Built on data,<br /><em>powered by people.</em>
          </h1>
          <p className="lp-hero-sub">
            Axon gives small businesses enterprise-grade intelligence — without the complexity. Surface the insights that matter, understand your customers, and make confident decisions every day.
          </p>
          <div className="lp-hero-ctas">
            <AnchorButton
              size="large"
              intent="primary"
              endIcon={<ArrowRight />}
              href="/login"
              text="Open your dashboard"
            />
            <AnchorButton size="large" variant="outlined" icon={<Play />} href="#how" text="See how it works" />
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
            <Card elevation={Elevation.FOUR} className="lp-dashboard-frame">
              <div className="lp-dash-titlebar">
                <div className="lp-dash-dot lp-dash-dot-r" />
                <div className="lp-dash-dot lp-dash-dot-y" />
                <div className="lp-dash-dot lp-dash-dot-g" />
              </div>
              <div className="lp-dash-body">
                <div className="lp-dash-sidebar">
                  <div className="lp-dash-sidebar-logo">
                    <AxonMark size={18} maskId="axon-mark-mockup" />
                    <span>Axon</span>
                  </div>
                  <div className="lp-dash-nav-item active">
                    <Dashboard size={14} />
                    Overview
                  </div>
                  <div className="lp-dash-nav-item">
                    <Star size={14} />
                    Leads
                  </div>
                  <div className="lp-dash-nav-item">
                    <ColumnLayout size={14} />
                    Pipeline
                  </div>
                  <div className="lp-dash-nav-item">
                    <Tick size={14} />
                    Tasks
                  </div>
                  <div className="lp-dash-nav-item">
                    <Dollar size={14} />
                    Expenses
                  </div>
                  <div className="lp-dash-nav-item">
                    <Document size={14} />
                    Invoices
                  </div>
                  <div className="lp-dash-nav-item">
                    <Book size={14} />
                    Bookkeeping
                  </div>
                  <div className="lp-dash-nav-item">
                    <Cog size={14} />
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
                        <TrendingUp size={10} color="var(--color-moss)" />
                        +$18k this week
                      </div>
                    </div>
                    <div className="lp-dash-metric">
                      <div className="lp-dash-metric-label">Scored Leads</div>
                      <div className="lp-dash-metric-value">1,847</div>
                      <div className="lp-dash-metric-delta">
                        <TrendingUp size={10} color="var(--color-moss)" />
                        +124 this run
                      </div>
                    </div>
                    <div className="lp-dash-metric">
                      <div className="lp-dash-metric-label">Tasks Due Today</div>
                      <div className="lp-dash-metric-value">8</div>
                      <div className="lp-dash-metric-delta neg">
                        <TrendingDown size={10} color="var(--color-rose)" />
                        3 overdue
                      </div>
                    </div>
                    <div className="lp-dash-metric">
                      <div className="lp-dash-metric-label">Outstanding AR</div>
                      <div className="lp-dash-metric-value">$9,450</div>
                      <div className="lp-dash-metric-delta">
                        <TrendingUp size={10} color="var(--color-moss)" />
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
            </Card>
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
            <span className="lp-logo-item">&amp; More</span>
          </div>
        </div>
      </div>

      {/* ── Features ── */}
      <section className="lp-features-section" id="features">
        <div className="lp-container">
          <div className="lp-section-eyebrow">
            <Layers size={12} color="var(--color-accent)" />
            What Axon does
          </div>
          <h2 className="lp-section-heading">
            Everything a big enterprise has —<br />built for the way you actually work
          </h2>
          <p className="lp-section-sub">
            Axon connects your data sources, learns your business patterns, and delivers intelligence that feels less like a report and more like advice from a trusted partner.
          </p>
          <div className="lp-features-grid">
            <Card interactive elevation={Elevation.ONE} className="lp-feature-card">
              <div className="lp-feature-icon accent"><Star size={20} color="var(--color-accent)" /></div>
              <h3 className="lp-feature-name">Lead scoring engine</h3>
              <p className="lp-feature-desc">
                Axon pulls public property records for your target ZIP codes and scores every address by
                opportunity size, condition signals, and vertical fit. Know who to call before you dial.
              </p>
            </Card>
            <Card interactive elevation={Elevation.ONE} className="lp-feature-card">
              <div className="lp-feature-icon ocean"><ColumnLayout size={20} color="var(--color-ocean-d)" /></div>
              <h3 className="lp-feature-name">Visual pipeline</h3>
              <p className="lp-feature-desc">
                Drag leads through your stages — New, Contacted, Quoted, Won — on a live Kanban board.
                See your total pipeline value update in real time as deals move forward.
              </p>
            </Card>
            <Card interactive elevation={Elevation.ONE} className="lp-feature-card">
              <div className="lp-feature-icon moss"><Tick size={20} color="var(--color-moss)" /></div>
              <h3 className="lp-feature-name">Task management</h3>
              <p className="lp-feature-desc">
                Create tasks linked to specific properties and leads, set priorities from low to urgent,
                and get overdue alerts. Your follow-up list and your CRM, finally in sync.
              </p>
            </Card>
            <Card interactive elevation={Elevation.ONE} className="lp-feature-card">
              <div className="lp-feature-icon gold"><Dollar size={20} color="var(--color-gold)" /></div>
              <h3 className="lp-feature-name">Expense tracker</h3>
              <p className="lp-feature-desc">
                Log every business expense by category — fuel, materials, subcontractors, and more. Flag
                tax-deductible items and export a clean CSV for your accountant any time.
              </p>
            </Card>
            <Card interactive elevation={Elevation.ONE} className="lp-feature-card">
              <div className="lp-feature-icon plum"><Document size={20} color="var(--color-plum)" /></div>
              <h3 className="lp-feature-name">Invoicing &amp; accounts receivable</h3>
              <p className="lp-feature-desc">
                Build invoices with line items, record partial payments, and pull an AR aging report with
                one click. Know exactly who owes you, and how long they&apos;ve owed it.
              </p>
            </Card>
            <Card interactive elevation={Elevation.ONE} className="lp-feature-card">
              <div className="lp-feature-icon rose"><Book size={20} color="var(--color-rose)" /></div>
              <h3 className="lp-feature-name">Bookkeeping &amp; P&amp;L</h3>
              <p className="lp-feature-desc">
                See your monthly profit and loss and per-property job costing — revenue versus expenses
                and margin per job. No separate accounting app needed.
              </p>
            </Card>
          </div>
        </div>
      </section>

      {/* ── Split: Pipeline ── */}
      <section className="lp-section" id="pipeline">
        <div className="lp-container">
          <div className="lp-split-section">
            <div>
              <div className="lp-section-eyebrow">
                <Star size={12} color="var(--color-accent)" />
                Lead intelligence
              </div>
              <h2 className="lp-section-heading">Your data knows what&#39;s coming -<br/> now so do you</h2>
              <p className="lp-section-sub">
                Axons intelligence layer reads patterns across your business and flags what needs your attention — not what already happened.
              </p>
              <div className="lp-split-points">
                <div className="lp-split-point">
                  <div className="lp-split-point-icon"><Notifications size={16} /></div>
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
                  <div className="lp-split-point-icon"><Locate size={16} /></div>
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
              <Card elevation={Elevation.TWO} className="lp-insight-panel">
                <div className="lp-insight-header">
                  <span className="lp-insight-title">Top scored leads — 77007</span>
                  <Tag minimal intent="primary">124 new</Tag>
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
              </Card>
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
              <Map size={12} color="var(--color-accent)" />
              How it works
            </div>
            <h2 className="lp-section-heading">From territory to closed job — in one workflow</h2>
            <p className="lp-section-sub" style={{ margin: '0 auto' }}>
              No data team. No complex setup. Point Axon at your ZIP codes and vertical, and it handles
              the rest — from lead discovery to invoicing.
            </p>
          </div>
          <div className="lp-how-steps">
            <Card elevation={Elevation.ONE} className="lp-how-step">
              <div className="lp-how-step-number active">01</div>
              <h3 className="lp-how-step-title">Set your territory</h3>
              <p className="lp-how-step-desc">
                Choose your ZIP codes and service vertical. Schedule scoring runs daily, weekly, or on
                demand — Axon pulls fresh property data automatically.
              </p>
            </Card>
            <Card elevation={Elevation.ONE} className="lp-how-step">
              <div className="lp-how-step-number">02</div>
              <h3 className="lp-how-step-title">Work your ranked leads</h3>
              <p className="lp-how-step-desc">
                Open the lead table sorted by score, filter to grade-A properties, and add the best ones
                to your Kanban pipeline. Assign tasks, take notes, and track every touchpoint.
              </p>
            </Card>
            <Card elevation={Elevation.ONE} className="lp-how-step">
              <div className="lp-how-step-number">03</div>
              <h3 className="lp-how-step-title">Invoice, track, and close the books</h3>
              <p className="lp-how-step-desc">
                When you win a job, create an invoice in seconds. Log your expenses, monitor your AR,
                and check your P&amp;L — Axon ties the whole job together so nothing falls through the cracks.
              </p>
            </Card>
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
            <AnchorButton size="large" intent="primary" href="/login" text="Open your dashboard" />
            <AnchorButton size="large" variant="minimal" href="#how" text="See how it works" className="lp-cta-ghost" />
          </div>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="lp-footer">
        <div className="lp-container">
          <div className="lp-footer-inner">
            <div>
              <span className="lp-footer-wordmark">
                <AxonMark size={20} maskId="axon-mark-footer" />
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
                <li><a href="/login">Lead scoring</a></li>
                <li><a href="/login">Kanban pipeline</a></li>
                <li><a href="/login">Invoicing &amp; AR</a></li>
                <li><a href="/login">Bookkeeping</a></li>
              </ul>
            </div>
            <div>
              <div className="lp-footer-col-title">Account</div>
              <ul className="lp-footer-links">
                <li><a href="/login">Sign in</a></li>
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
    </>
  )
}
