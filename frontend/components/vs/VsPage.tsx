import Link from 'next/link'
import { ArrowRight, Check, X } from 'lucide-react'
import { VS_COMPETITORS, type VsCompetitor } from '@/lib/vsData'
import { AxonWordmark } from './AxonWordmark'

/**
 * Shared frame for the /vs comparison pages (audit D5.3). Persuade surface in
 * the landing's own visual world: same tokens, same .lp-vs table language.
 * All copy comes from lib/vsData.ts, where the defensibility rule lives.
 */
export function VsPage({ data }: { data: VsCompetitor }) {
  const others = VS_COMPETITORS.filter(c => c.slug !== data.slug)
  return (
    <div className="lp">
      <nav className="lp-nav">
        <div className="lp-container lp-nav-inner">
          <Link className="lp-nav-logo" href="/" aria-label="Axon home">
            <AxonWordmark />
          </Link>
          <div className="lp-nav-actions">
            <a className="lp-btn lp-btn-ghost" href="/login">Sign In</a>
            <a className="lp-btn lp-btn-accent" href="/signup">Start Free</a>
          </div>
        </div>
      </nav>

      <header className="lp-container vsp-hero">
        <div className="lp-eyebrow">Compare · checked {data.checked}</div>
        <h1 className="vsp-h1">Axon vs {data.name}</h1>
        <p className="vsp-verdict">{data.verdict}</p>
      </header>

      <main className="lp-container">
        <div className="lp-vs-wrap" style={{ marginTop: 0 }}>
          <div className="lp-vs" role="table" aria-label={`How Axon compares with ${data.name}`}>
            <div className="lp-vs-row lp-vs-head" role="row">
              <div className="lp-vs-cell" role="columnheader">
                <span className="lp-vs-dim">Side by side</span>
              </div>
              <div className="lp-vs-cell" role="columnheader">
                <b>{data.name}</b>
                <span>{data.sub}</span>
              </div>
              <div className="lp-vs-cell" role="columnheader">
                <span className="lp-vs-flag">The local one</span>
                <b className="lp-vs-brand">Axon</b>
                <span>Your ranked territory list</span>
              </div>
            </div>
            {data.rows.map(row => (
              <div className="lp-vs-row" role="row" key={row.label}>
                <div className="lp-vs-cell lp-vs-rowlabel" role="rowheader">
                  <strong>{row.label}</strong>
                </div>
                <div className="lp-vs-cell" role="cell">
                  <span className="lp-vs-mark lp-vs-no"><X size={12} /></span>
                  <span>{row.them}</span>
                </div>
                <div className="lp-vs-cell" role="cell">
                  <span className="lp-vs-mark lp-vs-yes"><Check size={12} /></span>
                  <span>{row.axon}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <section className="vsp-honest">
          <h2>When {data.name} is the better fit</h2>
          <ul>
            {data.themBetterWhen.map(item => <li key={item}>{item}</li>)}
          </ul>
        </section>

        <p className="lp-vs-foot">{data.footnote}</p>

        <section className="vsp-cta">
          <h2>See your own ZIP ranked — free, no email</h2>
          <p>
            Type a Harris County ZIP on the homepage and read the scored list, or open the
            full live demo. 14 days free after that, no credit card.
          </p>
          <div className="lp-cta-actions" style={{ justifyContent: 'flex-start' }}>
            <Link className="lp-btn lp-btn-accent lp-btn-lg" href="/#zip-sample">Preview Your ZIP</Link>
            <a className="lp-btn lp-btn-outline lp-btn-lg" href="/preview">Try the Live Demo</a>
          </div>
        </section>

        <p className="vsp-crosslinks">
          Also compare:{' '}
          {others.map((c, i) => (
            <span key={c.slug}>
              {i > 0 && ' \u00b7 '}
              <Link href={`/vs/${c.slug}`}>Axon vs {c.name}</Link>
            </span>
          ))}
          {' \u00b7 '}<Link href="/">Back to the homepage <ArrowRight size={12} style={{ verticalAlign: '-1px' }} /></Link>
        </p>
      </main>
    </div>
  )
}
