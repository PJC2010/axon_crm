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
