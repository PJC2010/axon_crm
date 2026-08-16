'use client'
import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Building2, Loader2, RefreshCw } from 'lucide-react'
import { archiveNonResidential, getNonResidentialAudit } from '@/lib/api'
import type { NonResidentialAudit, NonResidentialSample } from '@/lib/types'

/**
 * "Not a home" audit — finds leads the county roll seeded that are not houses.
 *
 * The free HCAD seed takes every *parcel* in a ZIP, so shopping centres,
 * churches, school-district land and vacant lots arrive alongside the homes,
 * get scored, and sit in the pipeline as live leads.
 *
 * Three deliberate choices in this UI, all for the same reason — archiving is
 * destructive and the underlying rule can be wrong:
 *
 *   Evidence before action. The report loads on mount and shows real example
 *   rows with the reason each was flagged, so the call can be checked before
 *   anything is archived.
 *   Confirm on a real number. The button runs a dry run first and asks for
 *   confirmation against the count the server actually computed, not the count
 *   this component last rendered.
 *   Review is never actionable. `review`-tier reasons are shown and counted but
 *   have no button; the server rejects them too.
 */
export function NonResidentialSection() {
  const [audit, setAudit] = useState<NonResidentialAudit | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setAudit(await getNonResidentialAudit())
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not load the audit')
    } finally {
      setLoading(false)
    }
  }, [])

  // The initial fetch is written out rather than calling load(): load() sets
  // state synchronously (the spinner, clearing the error), which inside an
  // effect body causes a cascading render. Here every setState happens in a
  // promise callback, and `active` drops the result if the tab unmounts while
  // the request is still open.
  useEffect(() => {
    let active = true
    getNonResidentialAudit()
      .then(a => { if (active) setAudit(a) })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : 'Could not load the audit')
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  async function handleArchive() {
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      // Confirm against the server's own count, not the rendered one — the
      // report may be minutes old, and a pipeline run may have added rows.
      const plan = await archiveNonResidential({ dry_run: true })
      if (plan.would_archive === 0) {
        setResult('Nothing to archive — no leads match the exclude rules.')
        return
      }
      const ok = window.confirm(
        `Archive ${plan.would_archive.toLocaleString()} lead${plan.would_archive === 1 ? '' : 's'} ` +
        `that don't look like homes?\n\n` +
        `They're hidden, not deleted — notes and history are kept, they stop ` +
        `costing you data-provider lookups, and you can restore any of them ` +
        `from the archived view.`,
      )
      if (!ok) return
      const done = await archiveNonResidential({})
      setResult(`Archived ${done.archived_count.toLocaleString()} lead${done.archived_count === 1 ? '' : 's'}.`)
      await load()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Archive failed')
    } finally {
      setBusy(false)
    }
  }

  // The server never archives leads a rep has already worked, so the button
  // must promise what it will actually do — otherwise the label, the dry-run
  // confirmation and the result line are three different numbers.
  const archivable = Math.max(0, (audit?.excludable ?? 0) - (audit?.protected ?? 0))

  const exclude = Object.entries(audit?.by_reason ?? {})
    .filter(([, r]) => r.tier === 'exclude' && r.count > 0)
  const review = Object.entries(audit?.by_reason ?? {})
    .filter(([, r]) => r.tier === 'review' && r.count > 0)

  return (
    <section>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <Building2 size={14} strokeWidth={1.5} style={{ color: 'var(--color-accent)' }} />
        <h2 className="t-eyebrow" style={{ margin: 0 }}>Leads that aren&apos;t homes</h2>
      </div>
      <p style={{ margin: '0 0 12px', fontSize: 13, color: 'var(--color-ink-500)', lineHeight: 1.5 }}>
        County records cover every parcel, not just houses — so shopping centres,
        churches, school land and empty lots can arrive with your leads. This
        finds them. Nothing is deleted: archived leads keep their notes and
        history, stop costing you data lookups, and can be restored at any time.
      </p>

      {loading && (
        <p style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--color-ink-500)' }}>
          <Loader2 size={13} className="animate-spin" /> Checking your leads…
        </p>
      )}

      {!loading && audit && (
        <>
          <Summary audit={audit} />

          {exclude.length > 0 && (
            <ReasonList
              title="Safe to archive"
              hint="These can't be houses."
              reasons={exclude}
            />
          )}
          {review.length > 0 && (
            <ReasonList
              title="Worth a look"
              hint="A real home can look like this, so these are never archived automatically — open one to decide."
              reasons={review}
            />
          )}

          {audit.samples.length > 0 && (
            <Examples samples={audit.samples} labels={audit.by_reason} />
          )}

          {/* Recheck sits outside the archivable guard: it is non-destructive,
              and it is most wanted exactly when there is nothing to archive —
              right after a successful cleanup, or on a report that found only
              review-tier rows. */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 16, flexWrap: 'wrap' }}>
            {archivable > 0 && (
              <button
                onClick={handleArchive}
                disabled={busy}
                className="btn-primary"
                style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 36, padding: '0 14px', fontSize: 13 }}
              >
                {busy
                  ? <Loader2 size={13} strokeWidth={1.5} className="animate-spin" />
                  : <Building2 size={13} strokeWidth={1.5} />}
                {busy ? 'Working…' : `Archive ${archivable.toLocaleString()} non-home lead${archivable === 1 ? '' : 's'}`}
              </button>
            )}
            <button
              onClick={() => void load()}
              disabled={busy || loading}
              className="btn-secondary"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 36, padding: '0 14px', fontSize: 13 }}
            >
              <RefreshCw size={13} strokeWidth={1.5} /> Recheck
            </button>
          </div>
        </>
      )}

      {result && (
        <p style={{ margin: '12px 0 0', fontSize: 13, color: 'var(--color-ink-500)' }}>{result}</p>
      )}
      {error && (
        <p style={{ margin: '12px 0 0', fontSize: 12, color: 'var(--color-danger)' }}>{error}</p>
      )}
    </section>
  )
}

function Summary({ audit }: { audit: NonResidentialAudit }) {
  const clean = audit.flagged === 0
  return (
    <div
      style={{
        display: 'flex', gap: 24, flexWrap: 'wrap', padding: '12px 14px',
        marginBottom: 14, borderRadius: 'var(--radius-card)',
        background: 'var(--color-surface-sunken, rgba(127,127,127,0.06))',
      }}
    >
      <Stat label="Leads checked" value={audit.properties} />
      <Stat label="Not homes" value={audit.excludable} emphasis={audit.excludable > 0} />
      {audit.spend_at_risk.billable_rows > 0 && (
        <Stat
          label="Still billing lookups"
          value={audit.spend_at_risk.billable_rows}
          emphasis
        />
      )}
      {audit.protected > 0 && (
        <Stat label="Skipped — already worked" value={audit.protected} />
      )}
      {audit.already_archived > 0 && <Stat label="Archived earlier" value={audit.already_archived} />}
      {clean && (
        <p style={{ margin: 0, alignSelf: 'center', fontSize: 13, color: 'var(--color-ink-500)' }}>
          Nothing looks out of place.
        </p>
      )}
    </div>
  )
}

function Stat({ label, value, emphasis }: { label: string; value: number; emphasis?: boolean }) {
  return (
    <div>
      <div
        style={{
          fontSize: 20, fontWeight: 600, lineHeight: 1.2,
          color: emphasis ? 'var(--color-warning, var(--color-accent))' : 'var(--color-ink-900)',
        }}
      >
        {value.toLocaleString()}
      </div>
      <div style={{ fontSize: 11, color: 'var(--color-ink-500)', marginTop: 2 }}>{label}</div>
    </div>
  )
}

function ReasonList({
  title, hint, reasons,
}: {
  title: string
  hint: string
  reasons: [string, { count: number; label: string }][]
}) {
  return (
    <div style={{ marginBottom: 14 }}>
      <p style={{ margin: '0 0 2px', fontSize: 12, fontWeight: 600, color: 'var(--color-ink-900)' }}>
        {title}
      </p>
      <p style={{ margin: '0 0 8px', fontSize: 12, color: 'var(--color-ink-500)' }}>{hint}</p>
      <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 4 }}>
        {reasons.map(([key, r]) => (
          <li key={key} style={{ display: 'flex', gap: 10, fontSize: 13, color: 'var(--color-ink-700, var(--color-ink-900))' }}>
            <span style={{ minWidth: 56, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
              {r.count.toLocaleString()}
            </span>
            <span style={{ color: 'var(--color-ink-500)' }}>{r.label}</span>
          </li>
        ))}
      </ul>
      {/* One row usually trips several reasons, so these do not sum to the total. */}
    </div>
  )
}

function Examples({
  samples, labels,
}: {
  samples: NonResidentialSample[]
  labels: Record<string, { label: string }>
}) {
  return (
    <details style={{ marginBottom: 4 }}>
      <summary style={{ cursor: 'pointer', fontSize: 13, color: 'var(--color-accent)' }}>
        Show {samples.length} example{samples.length === 1 ? '' : 's'}
      </summary>
      <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 10 }}>
        {samples.map(s => (
          <div key={s.id} style={{ fontSize: 12, lineHeight: 1.5 }}>
            <div style={{ fontWeight: 600, color: 'var(--color-ink-900)' }}>
              {s.address || '(no address)'}{s.zip ? `, ${s.zip}` : ''}
            </div>
            <div style={{ color: 'var(--color-ink-500)' }}>
              {[
                s.owner_name,
                s.square_footage ? `${s.square_footage.toLocaleString()} sqft` : null,
                s.estimated_value ? `$${s.estimated_value.toLocaleString()}` : null,
                s.score_grade ? `grade ${s.score_grade}` : null,
              ].filter(Boolean).join(' · ')}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--color-ink-500)', marginTop: 2 }}>
              <AlertTriangle size={11} strokeWidth={1.5} style={{ flexShrink: 0 }} />
              {s.reasons.map(r => labels[r]?.label ?? r).join('; ')}
            </div>
          </div>
        ))}
      </div>
    </details>
  )
}
