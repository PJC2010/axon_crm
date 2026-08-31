/**
 * Comparison-page data (audit D5.3). One rule governs every cell, the same one
 * the homepage table lives by: each claim must be defensible against the
 * competitor's own published model at the time of writing. Where a fact is not
 * published, the cell says so instead of guessing. `checked` is the month the
 * competitor's public pages were last reviewed — update it when re-verifying.
 */

export interface VsRow {
  label: string
  them: string
  axon: string
}

export interface VsCompetitor {
  slug: string
  name: string
  /** Their category, in their own framing. */
  sub: string
  title: string
  metaDescription: string
  /** 2\u20133 sentence plain-language verdict at the top of the page. */
  verdict: string
  rows: VsRow[]
  /** Honest cases where the competitor is the better choice. */
  themBetterWhen: string[]
  /** The footnote disclaimer, page-specific. */
  footnote: string
  checked: string
}

const AXON_TRIAL = '14 days free, no credit card, month to month \u2014 cancel anytime'

export const VS_COMPETITORS: VsCompetitor[] = [
  {
    slug: 'axon-vs-angi',
    name: 'Angi',
    sub: 'Shared-lead marketplace',
    title: 'Axon vs Angi \u2014 flat monthly territory list vs paying per shared lead',
    metaDescription:
      'Angi sells the same homeowner inquiry to several contractors at once, priced per lead. Axon builds a ranked list of every promising property in your Harris County ZIP codes for one flat monthly price. Side-by-side comparison.',
    verdict:
      'Angi and Axon solve different problems. Angi sells you homeowners who filled out a form \u2014 the same name goes to several pros, and you pay for each one, win or lose. Axon builds you a ranked list of every promising property in your Harris County ZIP codes from public records, for one flat monthly price. Nobody on an Axon list has raised a hand yet; nobody else is racing you to them either.',
    rows: [
      { label: 'How you pay', them: 'Per lead, win or lose \u2014 contractors report roughly $15\u2013$85 per shared lead', axon: 'One flat monthly price ($49\u2013$249), however many properties you work' },
      { label: 'Who else gets the same name', them: 'The same inquiry is shared with up to 4 pros', axon: 'Nobody \u2014 your list is built for your account alone' },
      { label: 'Where the list comes from', them: 'Whoever fills out the national form', axon: 'Every property in your ZIP codes, scored from Harris County appraisal records, permits, equity, and storm data' },
      { label: 'Why a name is on your list', them: 'No explanation', axon: 'Every score shows its signals \u2014 year built, equity, permits, storm exposure' },
      { label: 'Has the homeowner asked for a quote?', them: 'Yes \u2014 they filled out a form (and it went to your competitors too)', axon: 'No \u2014 the score tells you where to knock first; the call is yours to make' },
      { label: 'Trial and contract', them: 'Pay per lead from the first one', axon: AXON_TRIAL },
      { label: 'Who owns the customer', them: 'The platform \u2014 the relationship starts on their funnel', axon: 'You do \u2014 export every list, contact, and invoice anytime' },
    ],
    themBetterWhen: [
      'You want inbound only \u2014 homeowners who have already asked for quotes today, and you are willing to race other pros for them.',
      'You work outside Harris County, Texas, where Axon does not score yet.',
    ],
    footnote:
      'Angi does not publish a price list; the per-lead range above is what contractors report paying, with roofing and HVAC install leads at the top of the range. Angi is a trademark of its owner \u2014 no affiliation or endorsement implied. Check the numbers against your own last Angi invoice.',
    checked: 'August 2026',
  },
  {
    slug: 'axon-vs-salesrabbit',
    name: 'SalesRabbit',
    sub: 'Field sales / canvassing platform',
    title: 'Axon vs SalesRabbit \u2014 public-records scoring vs per-seat field sales',
    metaDescription:
      'SalesRabbit is a per-seat field sales platform whose DataGrid AI learns from your sales history. Axon scores every Harris County property from public records on day one \u2014 no CRM history, one flat price for the whole team.',
    verdict:
      'SalesRabbit is a door-to-door field sales platform: canvassing tools and DataGrid AI buyer scores that learn from your sales history \u2014 priced per seat, so the bill grows with your team. Axon starts from the other end: it scores every property in your Harris County ZIP codes from public records, so you get a ranked list on day one even if you have never used a CRM, and the whole team works it for one flat price.',
    rows: [
      { label: 'How you pay', them: 'Per seat \u2014 published Pro pricing around $49/user/mo (annual), with per-user add-ons reported at $19\u2013$31', axon: 'One flat monthly price ($49\u2013$249), your whole team included' },
      { label: 'What the score learns from', them: 'DataGrid AI buyer scores learn from your sales history', axon: 'Public records \u2014 county appraisal, permits, equity, storm data. No CRM history required' },
      { label: 'Day-one value', them: 'Scores improve as your reps log outcomes', axon: 'A ranked list the first day, before a single call is logged' },
      { label: 'Why a name is on your list', them: 'AI buyer score', axon: 'Every score shows its signals \u2014 open the property and read them' },
      { label: 'Local depth', them: 'National platform with weather data', axon: 'Harris County only \u2014 county appraisal rolls, Houston permits, local NOAA storm reports' },
      { label: 'Scale', them: '85,000+ users', axon: 'Built for Harris County service contractors specifically' },
      { label: 'Trial and pricing access', them: 'Demo consultation to get full pricing', axon: AXON_TRIAL },
    ],
    themBetterWhen: [
      'You run large door-knocking teams across many states and need canvassing management at national scale.',
      'You already have years of sales history in a CRM for its AI to learn from, and you work outside Harris County.',
    ],
    footnote:
      'SalesRabbit pricing and features as published on salesrabbit.com at the time of writing; add-on pricing as reported. SalesRabbit is a trademark of its owner \u2014 no affiliation or endorsement implied. Verify current pricing on their site.',
    checked: 'August 2026',
  },
  {
    slug: 'axon-vs-ladder',
    name: 'Ladder SmartTerritory',
    sub: 'Roofing territory intelligence',
    title: 'Axon vs Ladder SmartTerritory \u2014 county-deep scoring from $49 vs $499+',
    metaDescription:
      'Ladder SmartTerritory builds roofing knock lists from your existing deal data, starting at $499/mo. Axon scores every Harris County property from public records \u2014 no deal history needed \u2014 from $49/mo flat.',
    verdict:
      'Ladder SmartTerritory is the closest tool to Axon: roofing territory intelligence with daily knock lists and storm tracking. The differences are the inputs and the price. Ladder models territories from your existing deal data and starts at $499/mo; Axon scores from Harris County public records \u2014 so it works on day one with no deal history \u2014 and runs $49\u2013$249/mo flat, for every trade, not just roofing.',
    rows: [
      { label: 'How you pay', them: 'Starting at $499/mo as published', axon: 'One flat monthly price ($49\u2013$249)' },
      { label: 'What the model needs from you', them: 'Your existing deal data to model territories', axon: 'Nothing \u2014 scores come from public records, ranked list on day one' },
      { label: 'Trades covered', them: 'Roofing-specific', axon: 'Roofing, HVAC, solar, fencing, pool, and other Harris County service trades' },
      { label: 'Storm response', them: 'Storm tracking with daily knock lists', axon: 'Storm Mode \u2014 the morning after hail, the affected homes in your territory, already ranked' },
      { label: 'Why a name is on your list', them: 'Territory model output', axon: 'Every score shows its signals \u2014 year built, equity, permits, storm exposure' },
      { label: 'Local depth', them: 'National roofing coverage', axon: 'Harris County only \u2014 county appraisal rolls, Houston permits, local NOAA storm reports' },
      { label: 'Trial and contract', them: 'Not published', axon: AXON_TRIAL },
    ],
    themBetterWhen: [
      'You are a roofing company outside Harris County \u2014 Axon does not score your market yet.',
      'You have years of closed-deal data across many markets and want territories modeled from it at national scale.',
    ],
    footnote:
      'Ladder SmartTerritory pricing and features as published on their site at the time of writing. Ladder is a trademark of its owner \u2014 no affiliation or endorsement implied. Verify current pricing on their site.',
    checked: 'August 2026',
  },
]

export function getVsCompetitor(slug: string): VsCompetitor | undefined {
  return VS_COMPETITORS.find(c => c.slug === slug)
}
