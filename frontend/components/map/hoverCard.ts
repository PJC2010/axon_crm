/**
 * Hover preview for a property pin.
 *
 * Before this, finding out what a pin was cost a click, a `getLead()` round
 * trip, and a full drawer — just to discover it was the wrong house. Everything
 * shown here is already in the pin's feature properties, so the preview costs
 * nothing beyond a DOM write.
 *
 * ## Why a MapLibre Popup and not a positioned React node
 *
 * `Popup` already solves anchoring, edge-flipping and keeping the card glued to
 * a moving map. Re-implementing that with `map.project()` means recomputing
 * position on every frame of a pan and re-rendering React while the user drags —
 * for a card that shows four fields.
 *
 * ## Why the DOM is built by hand
 *
 * `setDOMContent`, never `setHTML`. Addresses and owner names are vendor- and
 * user-supplied, and MapLibre 6.4.1 exists partly because its HTML sanitizer had
 * a hole. Building nodes and assigning `textContent` can't inject markup at all,
 * which is a stronger guarantee than sanitizing a string. Colors come from CSS
 * variables rather than the resolved palette so this stays a pure DOM concern.
 */
import { GRADE_TOKENS, GRADE_ACTION, statusTokens, type Grade } from '@/lib/gradeColors'

export interface HoverFields {
  address: string
  grade: string
  score: number | null
  status: string
  signals: string
}

/** Read the fields the card needs off a pin feature's properties. */
export function hoverFieldsFrom(props: Record<string, unknown> | null | undefined): HoverFields | null {
  if (!props) return null
  return {
    address: String(props.address ?? ''),
    grade: String(props.grade ?? 'N'),
    score: props.score == null ? null : Number(props.score),
    status: String(props.status ?? ''),
    signals: String(props.signals ?? ''),
  }
}

function el(tag: string, style: Partial<CSSStyleDeclaration>, text?: string): HTMLElement {
  const node = document.createElement(tag)
  Object.assign(node.style, style)
  if (text != null) node.textContent = text   // never innerHTML — see the note above
  return node
}

function pill(text: string, fg: string, bg: string): HTMLElement {
  return el('span', {
    display: 'inline-flex', alignItems: 'center', padding: '2px 8px',
    borderRadius: 'var(--radius-pill)', background: bg, color: fg,
    fontSize: '11px', fontWeight: '600', whiteSpace: 'nowrap',
  }, text)
}

/**
 * Build the card body.
 *
 * Mirrors `ds/ScoreBadge` and `ds/StatusPill` rather than importing them: those
 * are React components and this has to hand MapLibre a detached DOM node. The
 * *colors* still come from the one shared source, which is the part that
 * actually drifts.
 */
export function buildHoverCard(f: HoverFields): HTMLElement {
  const root = el('div', {
    minWidth: '180px', maxWidth: '260px', padding: '10px 12px',
    background: 'var(--color-surface)', border: '1px solid var(--color-ink-200)',
    borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-pop)',
    fontFamily: 'var(--font-sans)', color: 'var(--color-ink-700)',
  })

  root.appendChild(el('div', {
    fontSize: '13px', fontWeight: '600', color: 'var(--color-ink-900)',
    marginBottom: '6px', lineHeight: '1.35',
  }, f.address || 'No address on file'))

  const row = el('div', { display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' })

  // Grades A–D get their badge; the signals-mode pseudo-grades (S/N) don't —
  // a pin that is only "has signals" has no grade to report.
  const g = f.grade.toUpperCase() as Grade
  if (GRADE_TOKENS[g]) {
    const label = f.score == null ? g : `${g} · ${Math.round(f.score)}`
    const badge = pill(label, GRADE_TOKENS[g].fg, GRADE_TOKENS[g].bg)
    badge.title = GRADE_ACTION[g]
    row.appendChild(badge)
  }

  if (f.status) {
    const s = statusTokens(f.status)
    row.appendChild(pill(s.label, s.fg, s.bg))
  }

  if (row.childElementCount) root.appendChild(row)

  if (f.signals) {
    root.appendChild(el('div', {
      marginTop: '7px', paddingTop: '7px', borderTop: '1px solid var(--color-ink-100)',
      fontSize: '11px', color: 'var(--color-ink-500)',
    }, `Recent signals: ${f.signals}`))
  }

  return root
}

// ── choropleth cells ─────────────────────────────────────────────────────────

export interface CellFields {
  name: string
  leads: number
  signals: number
  avgScore: number
  grades: { A: number; B: number; C: number; D: number }
}

export function cellFieldsFrom(props: Record<string, unknown> | null | undefined): CellFields | null {
  if (!props) return null
  const n = (v: unknown) => Number(v) || 0
  return {
    name: String(props.name ?? ''),
    leads: n(props.leads),
    signals: n(props.signal_count),
    avgScore: n(props.avg_score),
    grades: { A: n(props.grade_a), B: n(props.grade_b), C: n(props.grade_c), D: n(props.grade_d) },
  }
}

/**
 * Hover card for a choropleth cell.
 *
 * The grade counts driving the bar have been in every `/api/map/cells` response
 * since the endpoint was written and were never rendered — the cell's fill
 * collapsed all of them into a single average. But "twelve leads averaging 68"
 * is ambiguous in the way that matters: it could be twelve mediocre houses or
 * four excellent ones dragged down by eight poor ones, and those call for
 * completely different decisions.
 */
export function buildCellCard(f: CellFields): HTMLElement {
  const root = el('div', {
    minWidth: '170px', maxWidth: '240px', padding: '10px 12px',
    background: 'var(--color-surface)', border: '1px solid var(--color-ink-200)',
    borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-pop)',
    fontFamily: 'var(--font-sans)', color: 'var(--color-ink-700)',
  })

  root.appendChild(el('div', {
    fontSize: '13px', fontWeight: '600', color: 'var(--color-ink-900)', marginBottom: '2px',
  }, f.name || 'This block'))

  root.appendChild(el('div', {
    fontSize: '11px', color: 'var(--color-ink-500)', marginBottom: '7px',
  }, `${f.leads.toLocaleString()} lead${f.leads === 1 ? '' : 's'}`
    + (f.avgScore ? ` · avg ${Math.round(f.avgScore)}` : '')
    + (f.signals ? ` · ${f.signals} signal${f.signals === 1 ? '' : 's'}` : '')))

  // Stacked bar rather than four numbers: the mix is a proportion, and a
  // proportion is what a bar reads as at a glance.
  const total = f.grades.A + f.grades.B + f.grades.C + f.grades.D
  if (total > 0) {
    const bar = el('div', {
      display: 'flex', height: '6px', borderRadius: '3px',
      overflow: 'hidden', background: 'var(--color-ink-100)',
    })
    for (const g of ['A', 'B', 'C', 'D'] as const) {
      const count = f.grades[g]
      if (!count) continue
      const seg = el('div', {
        width: `${(count / total) * 100}%`,
        background: GRADE_TOKENS[g].fg,
      })
      seg.title = `${count} grade ${g}`
      bar.appendChild(seg)
    }
    root.appendChild(bar)

    const counts = el('div', {
      display: 'flex', gap: '8px', marginTop: '5px',
      fontSize: '10px', color: 'var(--color-ink-500)',
    })
    for (const g of ['A', 'B', 'C', 'D'] as const) {
      if (!f.grades[g]) continue
      const item = el('span', { display: 'inline-flex', alignItems: 'center', gap: '3px' })
      item.appendChild(el('span', {
        width: '6px', height: '6px', borderRadius: '50%', background: GRADE_TOKENS[g].fg,
      }))
      item.appendChild(el('span', {}, `${g} ${f.grades[g]}`))
      counts.appendChild(item)
    }
    root.appendChild(counts)
  }

  return root
}
