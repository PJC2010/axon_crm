import './landing.css'
import {
  Sparkles, ArrowRight, PlayCircle,
  LayoutDashboard, Zap, Users, TrendingUp, TrendingDown,
  BarChart2, Settings, Layers, Database, FileText, ShieldCheck,
  Bell, GitBranch, Target, Map, MessageSquare,
} from 'lucide-react'

export const metadata = {
  title: 'Axon — Built on data, focused on people',
  description: 'Axon gives small businesses enterprise-grade intelligence — without the complexity.',
}

export default function LandingPage() {
  return (
    <>
      {/* ── Navigation ── */}
      <nav className="lp-nav">
        <div className="lp-container lp-nav-inner">
          <a href="#" className="lp-nav-logo">
            <svg width="28" height="28" viewBox="0 0 40 40" fill="none">
              <path
                d="M4 32 C 12 32, 14 22, 22 22 C 30 22, 30 14, 38 6"
                stroke="var(--color-ink-900)" strokeWidth="2.5"
                strokeLinecap="round" strokeLinejoin="round" fill="none"
              />
              <circle cx="4" cy="32" r="3" fill="var(--color-ink-900)" />
              <circle cx="22" cy="22" r="4" fill="#ffffff" stroke="var(--color-ink-900)" strokeWidth="2.5" />
              <circle cx="38" cy="6" r="6" fill="var(--color-accent)" />
            </svg>
            <span className="lp-nav-wordmark">Axon</span>
          </a>
          <ul className="lp-nav-links">
            <li><a href="#features">Features</a></li>
            <li><a href="#insights">Insights</a></li>
            <li><a href="#how">How it works</a></li>
            <li><a href="#pricing">Pricing</a></li>
          </ul>
          <div className="lp-nav-actions">
            <a href="#" className="lp-btn lp-btn-ghost">Sign in</a>
            <a href="#" className="lp-btn lp-btn-dark">Start free trial</a>
          </div>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section className="lp-hero">
        <div className="lp-container">
          <div className="lp-hero-badge">
            <Sparkles size={12} />
            Now with predictive forecasting
          </div>
          <h1 className="lp-hero-heading">
            Built on data,<br /><em>focused on people.</em>
          </h1>
          <p className="lp-hero-sub">
            Axon gives small businesses enterprise-grade intelligence — without the complexity.
            Surface the insights that matter, understand your customers, and make confident decisions every day.
          </p>
          <div className="lp-hero-ctas">
            <a href="#" className="lp-btn lp-btn-accent lp-btn-lg">
              Get started free
              <ArrowRight size={16} />
            </a>
            <a href="#" className="lp-btn lp-btn-outline lp-btn-lg">
              <PlayCircle size={16} />
              Watch a demo
            </a>
          </div>
          <div className="lp-hero-trust">
            <div className="lp-hero-trust-avatars">
              <span style={{ background: 'var(--color-moss)' }}>MR</span>
              <span style={{ background: 'var(--color-ocean-d)' }}>JK</span>
              <span style={{ background: 'var(--color-plum)' }}>TL</span>
              <span style={{ background: 'var(--color-accent)' }}>AS</span>
            </div>
            <span>Trusted by 2,400+ small business owners</span>
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
                    <span>Axon</span>
                  </div>
                  <div className="lp-dash-nav-item active">
                    <LayoutDashboard size={14} />
                    Overview
                  </div>
                  <div className="lp-dash-nav-item">
                    <Zap size={14} />
                    Insights
                  </div>
                  <div className="lp-dash-nav-item">
                    <Users size={14} />
                    Connections
                  </div>
                  <div className="lp-dash-nav-item">
                    <TrendingUp size={14} />
                    Forecasts
                  </div>
                  <div className="lp-dash-nav-item">
                    <BarChart2 size={14} />
                    Reports
                  </div>
                  <div className="lp-dash-nav-item">
                    <Settings size={14} />
                    Settings
                  </div>
                </div>
                <div className="lp-dash-main">
                  <div className="lp-dash-topbar">
                    <span className="lp-dash-title">Good morning, Maria</span>
                    <span className="lp-dash-date">May 29, 2026</span>
                  </div>
                  <div className="lp-dash-metrics">
                    <div className="lp-dash-metric">
                      <div className="lp-dash-metric-label">Revenue MTD</div>
                      <div className="lp-dash-metric-value">$84,210</div>
                      <div className="lp-dash-metric-delta">
                        <TrendingUp size={10} />
                        +12.4%
                      </div>
                    </div>
                    <div className="lp-dash-metric">
                      <div className="lp-dash-metric-label">Active clients</div>
                      <div className="lp-dash-metric-value">347</div>
                      <div className="lp-dash-metric-delta">
                        <TrendingUp size={10} />
                        +8 this week
                      </div>
                    </div>
                    <div className="lp-dash-metric">
                      <div className="lp-dash-metric-label">Avg. deal size</div>
                      <div className="lp-dash-metric-value">$2,430</div>
                      <div className="lp-dash-metric-delta neg">
                        <TrendingDown size={10} />
                        −3.1%
                      </div>
                    </div>
                    <div className="lp-dash-metric">
                      <div className="lp-dash-metric-label">Retention rate</div>
                      <div className="lp-dash-metric-value">94.2%</div>
                      <div className="lp-dash-metric-delta">
                        <TrendingUp size={10} />
                        +1.8 pts
                      </div>
                    </div>
                  </div>
                  <div className="lp-dash-charts">
                    <div className="lp-dash-chart-card">
                      <div className="lp-dash-chart-label">Monthly revenue</div>
                      <div className="lp-chart-bars">
                        <div className="lp-chart-bar" style={{ height: '45%' }} />
                        <div className="lp-chart-bar" style={{ height: '55%' }} />
                        <div className="lp-chart-bar" style={{ height: '40%' }} />
                        <div className="lp-chart-bar" style={{ height: '65%' }} />
                        <div className="lp-chart-bar" style={{ height: '58%' }} />
                        <div className="lp-chart-bar" style={{ height: '72%' }} />
                        <div className="lp-chart-bar hi" style={{ height: '88%' }} />
                      </div>
                    </div>
                    <div className="lp-dash-chart-card">
                      <div className="lp-dash-chart-label">Client engagement trend</div>
                      <div style={{ height: 80, display: 'flex', alignItems: 'center' }}>
                        <svg viewBox="0 0 200 64" fill="none" style={{ width: '100%', height: '100%' }}>
                          <path
                            d="M0 48 C30 44 50 36 80 30 C110 24 140 20 160 16 C175 13 190 10 200 8"
                            stroke="var(--color-accent)" strokeWidth="2" fill="none"
                          />
                          <path
                            d="M0 48 C30 44 50 36 80 30 C110 24 140 20 160 16 C175 13 190 10 200 8 L200 64 L0 64Z"
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

      {/* ── Logo strip ── */}
      <div className="lp-logos-section">
        <div className="lp-container">
          <p className="lp-logos-label">Trusted by businesses across industries</p>
          <div className="lp-logos-row">
            <span className="lp-logo-item">Hargrove Realty</span>
            <span className="lp-logo-item">Bellmont Legal</span>
            <span className="lp-logo-item">Sutton &amp; Co.</span>
            <span className="lp-logo-item">Meridian Consulting</span>
            <span className="lp-logo-item">Calloway Clinic</span>
            <span className="lp-logo-item">Ridgeline Retail</span>
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
            Axon connects your data sources, learns your business patterns, and delivers intelligence that
            feels less like a report and more like advice from a trusted partner.
          </p>
          <div className="lp-features-grid">
            <div className="lp-feature-card">
              <div className="lp-feature-icon accent"><Zap size={20} /></div>
              <h3 className="lp-feature-name">Predictive insights</h3>
              <p className="lp-feature-desc">
                Axon surfaces what matters next — revenue at risk, customers likely to churn, and emerging
                opportunities — before they become urgent.
              </p>
            </div>
            <div className="lp-feature-card">
              <div className="lp-feature-icon ocean"><Users size={20} /></div>
              <h3 className="lp-feature-name">Personal connections</h3>
              <p className="lp-feature-desc">
                Understand each client relationship at a glance. See communication history, engagement
                signals, and next-best actions in one place.
              </p>
            </div>
            <div className="lp-feature-card">
              <div className="lp-feature-icon moss"><TrendingUp size={20} /></div>
              <h3 className="lp-feature-name">Revenue forecasting</h3>
              <p className="lp-feature-desc">
                Accurate 30, 60, and 90-day forecasts built from your actual pipeline — not spreadsheet
                guesses. Know where you stand before month-end.
              </p>
            </div>
            <div className="lp-feature-card">
              <div className="lp-feature-icon gold"><Database size={20} /></div>
              <h3 className="lp-feature-name">Unified data hub</h3>
              <p className="lp-feature-desc">
                Connect your CRM, accounting tools, and marketing platforms. Axon normalizes everything
                into a single source of truth — no spreadsheets required.
              </p>
            </div>
            <div className="lp-feature-card">
              <div className="lp-feature-icon plum"><FileText size={20} /></div>
              <h3 className="lp-feature-name">Automated reporting</h3>
              <p className="lp-feature-desc">
                Board-ready reports and weekly digests — written in plain language, delivered on schedule.
                Spend less time compiling and more time deciding.
              </p>
            </div>
            <div className="lp-feature-card">
              <div className="lp-feature-icon rose"><ShieldCheck size={20} /></div>
              <h3 className="lp-feature-name">Enterprise-grade security</h3>
              <p className="lp-feature-desc">
                SOC 2 Type II certified. Role-based access, audit logs, and encrypted-at-rest storage — the
                same protections Fortune 500 companies demand.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── Split: Insights ── */}
      <section className="lp-section" id="insights">
        <div className="lp-container">
          <div className="lp-split-section">
            <div>
              <div className="lp-section-eyebrow">
                <Zap size={12} />
                Predictive insights
              </div>
              <h2 className="lp-section-heading">Your data knows what&apos;s coming — now so do you</h2>
              <p className="lp-section-sub">
                Axon&apos;s intelligence layer reads patterns across your business and flags what needs your
                attention — not what already happened.
              </p>
              <div className="lp-split-points">
                <div className="lp-split-point">
                  <div className="lp-split-point-icon"><Bell size={16} /></div>
                  <div className="lp-split-point-text">
                    <strong>Proactive alerts</strong>
                    <span>
                      Get notified when a high-value client goes quiet, a deal stalls, or a revenue target
                      looks at risk — with context on why.
                    </span>
                  </div>
                </div>
                <div className="lp-split-point">
                  <div className="lp-split-point-icon"><GitBranch size={16} /></div>
                  <div className="lp-split-point-text">
                    <strong>Scenario modeling</strong>
                    <span>
                      Run &ldquo;what if&rdquo; forecasts in seconds. Model the impact of a new hire, a price change,
                      or a seasonal dip without a spreadsheet in sight.
                    </span>
                  </div>
                </div>
                <div className="lp-split-point">
                  <div className="lp-split-point-icon"><Target size={16} /></div>
                  <div className="lp-split-point-text">
                    <strong>Recommended actions</strong>
                    <span>
                      Axon doesn&apos;t just surface problems — it suggests what to do next, ranked by expected
                      impact on your goals.
                    </span>
                  </div>
                </div>
              </div>
            </div>
            <div>
              <div className="lp-insight-panel">
                <div className="lp-insight-header">
                  <span className="lp-insight-title">Today&apos;s insights</span>
                  <span className="lp-insight-badge">3 new</span>
                </div>
                <div className="lp-insight-list">
                  <div className="lp-insight-item">
                    <div className="lp-insight-item-dot" style={{ background: 'var(--color-accent)' }} />
                    <div style={{ flex: 1 }}>
                      <div className="lp-insight-item-headline">Calloway account may be at risk</div>
                      <div className="lp-insight-item-detail">
                        No engagement in 18 days — last contact was invoice-related. Historical pattern
                        suggests 40% churn risk.
                      </div>
                    </div>
                    <div className="lp-insight-item-metric">$14k</div>
                  </div>
                  <div className="lp-insight-item">
                    <div className="lp-insight-item-dot" style={{ background: 'var(--color-moss)' }} />
                    <div style={{ flex: 1 }}>
                      <div className="lp-insight-item-headline">Q3 revenue on track to beat forecast</div>
                      <div className="lp-insight-item-detail">
                        Pipeline coverage at 2.1× target. Strongest quarter since Q1 2025 if current close
                        rate holds.
                      </div>
                    </div>
                    <div className="lp-insight-item-metric">+18%</div>
                  </div>
                  <div className="lp-insight-item">
                    <div className="lp-insight-item-dot" style={{ background: 'var(--color-ocean-d)' }} />
                    <div style={{ flex: 1 }}>
                      <div className="lp-insight-item-headline">Expansion opportunity — Sutton &amp; Co.</div>
                      <div className="lp-insight-item-detail">
                        Usage patterns match clients who upgraded within 90 days. Recommend a check-in
                        this week.
                      </div>
                    </div>
                    <div className="lp-insight-item-metric">$8.4k</div>
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
              <span className="lp-proof-stat-value lp-proof-stat-accent">2,400+</span>
              <span className="lp-proof-stat-label">Small businesses<br />running on Axon</span>
            </div>
            <div className="lp-proof-stat">
              <span className="lp-proof-stat-value">94%</span>
              <span className="lp-proof-stat-label">Average customer<br />retention rate</span>
            </div>
            <div className="lp-proof-stat">
              <span className="lp-proof-stat-value lp-proof-stat-accent">4.2×</span>
              <span className="lp-proof-stat-label">Average ROI within<br />the first 6 months</span>
            </div>
            <div className="lp-proof-stat">
              <span className="lp-proof-stat-value">11 hrs</span>
              <span className="lp-proof-stat-label">Saved per week on<br />reporting and analysis</span>
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
            <h2 className="lp-section-heading">From setup to insight — in a single afternoon</h2>
            <p className="lp-section-sub" style={{ margin: '0 auto' }}>
              No dedicated data team. No six-month implementation. Axon connects to your existing tools
              and starts surfacing value immediately.
            </p>
          </div>
          <div className="lp-how-steps">
            <div className="lp-how-step">
              <div className="lp-how-step-number active">01</div>
              <h3 className="lp-how-step-title">Connect your data</h3>
              <p className="lp-how-step-desc">
                Link your CRM, accounting software, and marketing tools in minutes with pre-built
                integrations. No data team required.
              </p>
            </div>
            <div className="lp-how-step">
              <div className="lp-how-step-number">02</div>
              <h3 className="lp-how-step-title">Axon learns your business</h3>
              <p className="lp-how-step-desc">
                Our models analyze your historical patterns, set baselines, and calibrate to your industry
                and goals automatically.
              </p>
            </div>
            <div className="lp-how-step">
              <div className="lp-how-step-number">03</div>
              <h3 className="lp-how-step-title">Act on what matters</h3>
              <p className="lp-how-step-desc">
                Get your daily digest, answer questions in plain English, and make confident decisions with
                context you can trust.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── Testimonials ── */}
      <section className="lp-testimonials-section">
        <div className="lp-container">
          <div className="lp-section-eyebrow">
            <MessageSquare size={12} />
            From our customers
          </div>
          <h2 className="lp-section-heading">What a difference real intelligence makes</h2>
          <div className="lp-testimonials-grid">
            <div className="lp-testimonial-card">
              <p className="lp-testimonial-quote">
                &ldquo;Axon flagged that one of our best clients was disengaging before we even noticed. We
                reached out, found out there was an issue, fixed it — and kept a $40k account. That&apos;s not
                a dashboard. That&apos;s a business partner.&rdquo;
              </p>
              <div className="lp-testimonial-attr">
                <div className="lp-testimonial-avatar" style={{ background: 'var(--color-accent)' }}>MR</div>
                <div>
                  <div className="lp-testimonial-name">Maria Reyes</div>
                  <div className="lp-testimonial-role">Owner, Hargrove Realty Group</div>
                </div>
              </div>
            </div>
            <div className="lp-testimonial-card">
              <p className="lp-testimonial-quote">
                &ldquo;I used to spend half my Sunday building the Monday morning report. Now Axon sends it
                before I wake up — and it&apos;s better than anything I was putting together by hand.&rdquo;
              </p>
              <div className="lp-testimonial-attr">
                <div className="lp-testimonial-avatar" style={{ background: 'var(--color-moss)' }}>JK</div>
                <div>
                  <div className="lp-testimonial-name">James Kim</div>
                  <div className="lp-testimonial-role">Managing Partner, Bellmont Legal</div>
                </div>
              </div>
            </div>
            <div className="lp-testimonial-card">
              <p className="lp-testimonial-quote">
                &ldquo;We&apos;re a 12-person firm. We couldn&apos;t afford a data analyst. Axon gave us something
                better — intelligence that&apos;s specific to our clients, our numbers, and our goals.&rdquo;
              </p>
              <div className="lp-testimonial-attr">
                <div className="lp-testimonial-avatar" style={{ background: 'var(--color-plum)' }}>TL</div>
                <div>
                  <div className="lp-testimonial-name">Tara Lawson</div>
                  <div className="lp-testimonial-role">CEO, Meridian Consulting</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── CTA band ── */}
      <section className="lp-cta-section">
        <div className="lp-container">
          <h2 className="lp-cta-heading">
            Predictive insights,<br /><em>personal connections.</em>
          </h2>
          <div className="lp-cta-actions">
            <a href="#" className="lp-btn lp-btn-paper lp-btn-lg">Start your free trial</a>
            <a href="#" className="lp-btn lp-btn-ghost lp-btn-lg" style={{ color: 'rgba(255,255,255,0.7)' }}>
              Schedule a demo
            </a>
          </div>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="lp-footer">
        <div className="lp-container">
          <div className="lp-footer-inner">
            <div>
              <span className="lp-footer-wordmark">Axon</span>
              <p className="lp-footer-tagline">Built on data, focused on people.</p>
            </div>
            <div>
              <div className="lp-footer-col-title">Product</div>
              <ul className="lp-footer-links">
                <li><a href="#">Features</a></li>
                <li><a href="#">Insights</a></li>
                <li><a href="#">Pricing</a></li>
              </ul>
            </div>
            <div>
              <div className="lp-footer-col-title">Company</div>
              <ul className="lp-footer-links">
                <li><a href="#">About</a></li>
                <li><a href="#">Blog</a></li>
                <li><a href="#">Contact</a></li>
              </ul>
            </div>
            <div>
              <div className="lp-footer-col-title">Legal</div>
              <ul className="lp-footer-links">
                <li><a href="#">Privacy</a></li>
                <li><a href="#">Terms</a></li>
                <li><a href="#">Security</a></li>
              </ul>
            </div>
          </div>
          <div className="lp-footer-bottom">
            <span>&copy; 2026 Axon Intelligence, Inc. All rights reserved.</span>
            <span>Made with care for small business owners.</span>
          </div>
        </div>
      </footer>
    </>
  )
}
