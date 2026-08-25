// Data + pure logic for the interactive no-login demo at /preview.
//
// Unlike lib/previewData.ts (static fixtures for the /preview/dev component
// gallery), this module backs a *working* sample workspace: the demo page holds
// these leads in React state, and everything the visitor sees — KPIs, the
// weighted forecast, stage totals, the Kanban board, the "why this score"
// panel — is derived from that state through the pure helpers here. Drag a card
// and the numbers move, exactly like the real product.
//
// Dates are computed relative to "now" so the demo never goes stale (a fixture
// dated June reads as "untouched for 14 months" a year later). Scores are
// derived from the property facts through a miniature of the real scoring
// model, so a lead's grade always agrees with its "why this score" breakdown —
// including leads the visitor adds themselves.
import type {
  Category, ForecastData, Lead, LeadStatus, PipelineCardLead, ScoreExplanation, ScoreGrade,
} from './types'

export const DEMO_CATEGORIES: Category[] = [
  { value: 'hvac', label: 'HVAC' },
  { value: 'roofing', label: 'Roofing' },
  { value: 'epoxy_flooring', label: 'Epoxy flooring' },
  { value: 'pool_maintenance', label: 'Pool maintenance' },
  { value: 'solar', label: 'Solar' },
]

// Same keys/colors as the real board's fallback stages (app/pipeline/page.tsx).
export const DEMO_STAGES: { key: LeadStatus; label: string; color: string }[] = [
  { key: 'new',            label: 'New',            color: 'var(--color-ink-300)' },
  { key: 'contacted',      label: 'Contacted',      color: 'var(--color-ocean)' },
  { key: 'qualified',      label: 'Qualified',      color: 'var(--color-accent)' },
  { key: 'quote_sent',     label: 'Quote Sent',     color: 'var(--color-gold)' },
  { key: 'won',            label: 'Won',            color: 'var(--color-moss)' },
  { key: 'lost',           label: 'Lost',           color: 'var(--color-danger)' },
  { key: 'not_interested', label: 'Not Interested', color: 'var(--color-ink-200)' },
]

/** StatusSelect offers the full product vocabulary; the board doesn't carry a
 *  'converted' column (it's the non-property preset's word for won), so fold
 *  it into 'won' wherever leads are bucketed by stage. Without this a lead
 *  marked Converted silently vanishes from the board and every stat. */
export function canonicalStage(status: LeadStatus | string): string {
  return status === 'converted' ? 'won' : status
}

export const OPEN_STAGES: LeadStatus[] = ['new', 'contacted', 'qualified', 'quote_sent']

/** Close-probability weights per open stage — mirrors the product's forecast. */
export const STAGE_WEIGHTS: Record<string, number> = {
  new: 10, contacted: 25, qualified: 50, quote_sent: 75,
}

// Anchor relative dates to UTC day start so the server render and the client
// hydration compute identical scores/day-counts (a raw Date.now() could round
// a borderline score differently across the SSR→hydrate gap).
const DAY_MS = 86_400_000
const dayAnchor = () => Math.floor(Date.now() / DAY_MS) * DAY_MS
const daysAgo = (n: number) => new Date(dayAnchor() - n * DAY_MS).toISOString()

/* ── Miniature scoring model ──
   The same factor vocabulary the real scorer explains (equity, years in home,
   home value, owner occupancy, area income), with weights that sum to 1.0.
   Signals saturate at plausible ceilings so the numbers stay in 0–100. */

interface FactorDef {
  key: string
  label: string
  weight: number
  signal: (l: DemoFacts) => number
  describe: (l: DemoFacts) => string
}

export interface DemoFacts {
  estimated_value: number
  estimated_equity: number
  last_sale_date: string | null
  owner_occupied: boolean
  zip_median_income: number
}

function yearsSince(date: string | null): number {
  if (!date) return 0
  return Math.max(0, (dayAnchor() - new Date(date).getTime()) / (365.25 * DAY_MS))
}

const clamp01 = (n: number) => Math.max(0, Math.min(1, n))

export const DEMO_FACTORS: FactorDef[] = [
  {
    key: 'equity', label: 'Home equity', weight: 0.30,
    signal: l => clamp01(l.estimated_equity / 250_000),
    describe: l => `About $${Math.round(l.estimated_equity / 1000)}K in equity — owners with more equity can more easily fund a big-ticket job.`,
  },
  {
    key: 'sale_recency', label: 'Years in home', weight: 0.25,
    signal: l => clamp01(yearsSince(l.last_sale_date) / 15),
    describe: l => {
      const y = Math.round(yearsSince(l.last_sale_date))
      return y > 0
        ? `${y} year${y === 1 ? '' : 's'} since purchase — long-tenured owners replace aging systems more often.`
        : 'Recently purchased — new owners often invest in upgrades early.'
    },
  },
  {
    key: 'home_value', label: 'Home value', weight: 0.20,
    signal: l => clamp01(l.estimated_value / 600_000),
    describe: l => `A $${Math.round(l.estimated_value / 1000)}K home signals budget for premium work.`,
  },
  {
    key: 'owner_occupied', label: 'Owner occupied', weight: 0.15,
    signal: l => (l.owner_occupied ? 1 : 0.2),
    describe: l => l.owner_occupied
      ? 'The owner lives here, so they decide and pay for the work directly.'
      : 'Absentee owner — decisions route through a landlord or manager.',
  },
  {
    key: 'area_income', label: 'Area income', weight: 0.10,
    signal: l => clamp01(l.zip_median_income / 120_000),
    describe: l => `Median household income of $${(l.zip_median_income / 1000).toFixed(1)}K supports the estimated job value.`,
  },
]

export function scoreDemoLead(facts: DemoFacts): { score: number; grade: ScoreGrade } {
  const score = Math.round(
    DEMO_FACTORS.reduce((sum, f) => sum + f.weight * f.signal(facts) * 100, 0),
  )
  const grade: ScoreGrade = score >= 85 ? 'A' : score >= 70 ? 'B' : score >= 55 ? 'C' : 'D'
  return { score, grade }
}

const GRADE_SUMMARY: Record<ScoreGrade, (top: string) => string> = {
  A: top => `One of the strongest prospects on your list — ${top.toLowerCase()} leads the case for calling first.`,
  B: top => `A solid prospect worth a timely follow-up — ${top.toLowerCase()} is doing the heavy lifting here.`,
  C: top => `An average fit — ${top.toLowerCase()} helps, but other signals are middling. Pursue when you have capacity.`,
  D: () => 'Low fit on the signals we score — spend your time on the higher grades first.',
}

/** Build the full "why this score" payload from a lead's facts — the injected
 *  form WhyThisScore renders without an API call. */
export function buildDemoExplanation(lead: Lead): ScoreExplanation {
  const facts: DemoFacts = {
    estimated_value: lead.estimated_value ?? 0,
    estimated_equity: lead.estimated_equity ?? 0,
    last_sale_date: lead.last_sale_date,
    owner_occupied: lead.owner_occupied ?? false,
    zip_median_income: lead.zip_median_income ?? 0,
  }
  const factors = DEMO_FACTORS.map(f => ({
    key: f.key,
    label: f.label,
    description: f.describe(facts),
    weight: f.weight,
    signal: Number(f.signal(facts).toFixed(2)),
    contribution: Number((f.weight * f.signal(facts) * 100).toFixed(1)),
  }))
  const top = [...factors].sort((a, b) => b.contribution - a.contribution).slice(0, 3)
  const grade = (lead.score_grade ?? 'C') as ScoreGrade
  return {
    lead_id: lead.id,
    score: lead.lead_score ?? 0,
    grade,
    vertical: lead.vertical,
    is_default_profile: false,
    summary: GRADE_SUMMARY[grade](top[0]?.label ?? 'Home equity'),
    top_drivers: top.map(f => f.key),
    factors,
    vertical_description: DEMO_FACTORS.slice(0, 3).map(f => ({
      key: f.key, label: f.label, description: f.label, weight: f.weight,
    })),
    score_updated_at: daysAgo(3),
    weights_drift: false,
  }
}

/* ── The sample workspace ── */

// ZIP reference used both by fixtures and by leads the visitor adds.
export const DEMO_ZIPS: Record<string, { income: number; lat: number; lng: number }> = {
  '77005': { income: 145_000, lat: 29.7168, lng: -95.4265 },
  '77006': { income: 78_500,  lat: 29.7405, lng: -95.3950 },
  '77008': { income: 82_000,  lat: 29.7920, lng: -95.4000 },
  '77019': { income: 125_000, lat: 29.7565, lng: -95.4120 },
  '77074': { income: 52_000,  lat: 29.6780, lng: -95.5030 },
  '77096': { income: 71_000,  lat: 29.6850, lng: -95.4780 },
}

interface Seed {
  id: number
  address: string
  zip: string
  lat: number
  lng: number
  owner: string
  phone: string | null
  email: string | null
  year_built: number
  sqft: number
  garage: number
  value: number
  equity: number
  sale_date: string
  sale_price: number
  pool: boolean
  permits: number
  vertical: string
  status: LeadStatus
  job: number
  /** Days since the last stage move — drives the cooling chip + activity feel. */
  movedDaysAgo: number
  source: string
}

const SEEDS: Seed[] = [
  { id: 1,  address: '1842 Westheimer Rd', zip: '77006', lat: 29.7430, lng: -95.3985, owner: 'James Mitchell',  phone: '(713) 555-0142', email: 'jmitchell@example.com', year_built: 1987, sqft: 3400, garage: 2, value: 480_000, equity: 240_000, sale_date: '2013-04-12', sale_price: 295_000, pool: true,  permits: 0, vertical: 'hvac',            status: 'qualified',  job: 12_500, movedDaysAgo: 2,  source: 'hcad' },
  { id: 2,  address: '504 River Oaks Blvd', zip: '77019', lat: 29.7565, lng: -95.4190, owner: 'Patricia Nguyen', phone: '(713) 555-0287', email: 'pnguyen@example.com',  year_built: 1992, sqft: 4200, garage: 3, value: 680_000, equity: 320_000, sale_date: '2018-03-22', sale_price: 520_000, pool: false, permits: 1, vertical: 'epoxy_flooring',  status: 'quote_sent', job: 6_200,  movedDaysAgo: 3,  source: 'rentcast' },
  { id: 3,  address: '2901 Heights Blvd',  zip: '77008', lat: 29.7905, lng: -95.3985, owner: 'Robert Chen',     phone: null,             email: null,                   year_built: 1975, sqft: 2100, garage: 1, value: 340_000, equity: 200_000, sale_date: '2012-09-10', sale_price: 195_000, pool: false, permits: 0, vertical: 'hvac',            status: 'contacted',  job: 8_500,  movedDaysAgo: 7,  source: 'hcad' },
  { id: 4,  address: '7614 Bissonnet St',  zip: '77074', lat: 29.6743, lng: -95.4972, owner: 'Maria Lopez',     phone: '(832) 555-0198', email: null,                   year_built: 1968, sqft: 1850, garage: 1, value: 220_000, equity: 140_000, sale_date: '2008-11-04', sale_price: 145_000, pool: false, permits: 2, vertical: 'pool_maintenance', status: 'new',       job: 4_800,  movedDaysAgo: 1,  source: 'csv_import' },
  { id: 5,  address: '3310 Montrose Blvd', zip: '77006', lat: 29.7381, lng: -95.3906, owner: 'David Park',      phone: '(713) 555-0331', email: 'dpark@example.com',    year_built: 2001, sqft: 2800, garage: 2, value: 510_000, equity: 150_000, sale_date: '2021-07-15', sale_price: 420_000, pool: true,  permits: 0, vertical: 'solar',           status: 'new',        job: 18_000, movedDaysAgo: 2,  source: 'rentcast' },
  { id: 6,  address: '1218 Harvard St',    zip: '77008', lat: 29.7838, lng: -95.3963, owner: 'Angela Brooks',   phone: '(713) 555-0464', email: 'abrooks@example.com',  year_built: 1948, sqft: 2600, garage: 2, value: 560_000, equity: 310_000, sale_date: '2011-05-02', sale_price: 285_000, pool: false, permits: 1, vertical: 'roofing',         status: 'new',        job: 14_200, movedDaysAgo: 6,  source: 'hcad' },
  { id: 7,  address: '5502 Braeswood Blvd', zip: '77096', lat: 29.6851, lng: -95.4740, owner: 'Tom Rivera',     phone: '(832) 555-0272', email: null,                   year_built: 1972, sqft: 2300, garage: 2, value: 310_000, equity: 175_000, sale_date: '2013-02-18', sale_price: 176_000, pool: false, permits: 0, vertical: 'hvac',            status: 'contacted',  job: 9_100,  movedDaysAgo: 4,  source: 'hcad' },
  { id: 8,  address: '918 W 23rd St',      zip: '77008', lat: 29.8021, lng: -95.4093, owner: 'Sandra Kim',      phone: '(713) 555-0509', email: 'skim@example.com',     year_built: 1994, sqft: 2450, garage: 2, value: 430_000, equity: 205_000, sale_date: '2016-10-09', sale_price: 305_000, pool: false, permits: 1, vertical: 'roofing',         status: 'qualified',  job: 11_800, movedDaysAgo: 1,  source: 'rentcast' },
  { id: 9,  address: '2604 Sunset Blvd',   zip: '77005', lat: 29.7186, lng: -95.4230, owner: 'Frank Delgado',   phone: '(713) 555-0616', email: 'fdelgado@example.com', year_built: 1989, sqft: 3900, garage: 2, value: 720_000, equity: 390_000, sale_date: '2016-04-27', sale_price: 505_000, pool: true,  permits: 0, vertical: 'pool_maintenance', status: 'quote_sent', job: 7_400, movedDaysAgo: 5,  source: 'hcad' },
  { id: 10, address: '1120 Studewood St',  zip: '77008', lat: 29.7930, lng: -95.3925, owner: 'Priya Patel',     phone: '(832) 555-0733', email: 'ppatel@example.com',   year_built: 1955, sqft: 2200, garage: 1, value: 480_000, equity: 265_000, sale_date: '2014-08-30', sale_price: 240_000, pool: false, permits: 2, vertical: 'roofing',         status: 'contacted',  job: 13_600, movedDaysAgo: 1,  source: 'hcad' },
  { id: 11, address: '4212 Meyerwood Dr',  zip: '77096', lat: 29.6786, lng: -95.4830, owner: 'Gloria Hansen',   phone: '(713) 555-0821', email: null,                   year_built: 1966, sqft: 2050, garage: 2, value: 285_000, equity: 190_000, sale_date: '2009-06-14', sale_price: 138_000, pool: false, permits: 0, vertical: 'hvac',            status: 'won',        job: 9_800,  movedDaysAgo: 2,  source: 'hcad' },
  { id: 12, address: '1507 Marshall St',   zip: '77006', lat: 29.7402, lng: -95.3898, owner: "Kevin O'Neal",    phone: '(713) 555-0938', email: 'koneal@example.com',   year_built: 1998, sqft: 2700, garage: 2, value: 465_000, equity: 210_000, sale_date: '2017-01-20', sale_price: 350_000, pool: false, permits: 1, vertical: 'epoxy_flooring',  status: 'won',        job: 5_400,  movedDaysAgo: 9,  source: 'rentcast' },
  { id: 13, address: '8110 Sharpview Dr',  zip: '77074', lat: 29.6812, lng: -95.5108, owner: 'Denise Carter',   phone: '(832) 555-1045', email: 'dcarter@example.com',  year_built: 1979, sqft: 1980, garage: 2, value: 240_000, equity: 155_000, sale_date: '2007-03-12', sale_price: 118_000, pool: false, permits: 0, vertical: 'solar',           status: 'won',        job: 12_000, movedDaysAgo: 16, source: 'csv_import' },
  { id: 14, address: '6023 Grape St',      zip: '77096', lat: 29.6903, lng: -95.4869, owner: 'Walter Simms',    phone: null,             email: null,                   year_built: 1961, sqft: 1900, garage: 1, value: 265_000, equity: 120_000, sale_date: '2019-11-08', sale_price: 210_000, pool: false, permits: 0, vertical: 'hvac',            status: 'lost',       job: 7_200,  movedDaysAgo: 12, source: 'hcad' },
]

const NEIGHBORHOODS: Record<string, string> = {
  '77005': 'WEST UNIVERSITY',
  '77006': 'MONTROSE',
  '77008': 'HOUSTON HEIGHTS',
  '77019': 'RIVER OAKS SEC 1-3',
  '77074': 'SHARPSTOWN',
  '77096': 'MEYERLAND AREA',
}

function seedToLead(s: Seed): Lead {
  const facts: DemoFacts = {
    estimated_value: s.value,
    estimated_equity: s.equity,
    last_sale_date: s.sale_date,
    owner_occupied: true,
    zip_median_income: DEMO_ZIPS[s.zip].income,
  }
  const { score, grade } = scoreDemoLead(facts)
  return {
    id: s.id,
    account_number: `C-0${1000 + s.id}`,
    address: s.address, city: 'Houston', state: 'TX', zip: s.zip,
    latitude: s.lat, longitude: s.lng,
    year_built: s.year_built, square_footage: s.sqft, garage_spaces: s.garage,
    estimated_value: s.value, estimated_equity: s.equity,
    last_sale_date: s.sale_date, last_sale_price: s.sale_price,
    owner_name: s.owner, owner_occupied: true,
    contact_phone: s.phone, contact_email: s.email, contact_name: s.owner,
    contact_phone_alt: null, contact_email_alt: null, mailing_address: null,
    preferred_contact_method: null, best_time_to_call: null,
    zip_median_income: DEMO_ZIPS[s.zip].income, permit_count_24mo: s.permits,
    has_pool: s.pool, has_cracked_slab: false,
    lead_score: score, score_grade: grade, vertical: s.vertical,
    neighborhood_value_ratio: 1.1, neighborhood_value_pctile: 0.7, neighborhood_value_basis: 'cell',
    hcad_neighborhood_code: null, hcad_neighborhood_name: NEIGHBORHOODS[s.zip] ?? null,
    assigned_to: null, lead_source: s.source,
    status: s.status, estimated_job_value: s.job,
    stage_moved_at: daysAgo(s.movedDaysAgo),
    score_updated_at: daysAgo(3),
    created_at: daysAgo(s.movedDaysAgo + 8), updated_at: daysAgo(s.movedDaysAgo),
    archived_at: null,
  }
}

export function makeDemoLeads(): Lead[] {
  return SEEDS.map(seedToLead)
}

/** Create a full demo lead from the visitor's "New lead" form. Property facts
 *  are derived deterministically from the inputs so the resulting score (and
 *  its explanation) look plausible without asking for twelve fields. */
export function makeVisitorLead(
  id: number,
  input: { name: string; address: string; zip: string; vertical: string; jobValue: number },
): Lead {
  const zipInfo = DEMO_ZIPS[input.zip] ?? DEMO_ZIPS['77006']
  // Cheap stable hash of the address for variety without randomness.
  let h = 0
  for (const ch of input.address) h = (h * 31 + ch.charCodeAt(0)) % 9973
  const value = Math.min(750_000, Math.max(180_000, Math.round(zipInfo.income * 4 + input.jobValue * 8 + h * 20)))
  const equity = Math.round(value * (0.32 + (h % 30) / 100))
  const saleYearsAgo = 4 + (h % 14)
  const facts: DemoFacts = {
    estimated_value: value,
    estimated_equity: equity,
    last_sale_date: daysAgo(Math.round(saleYearsAgo * 365.25)),
    owner_occupied: true,
    zip_median_income: zipInfo.income,
  }
  const { score, grade } = scoreDemoLead(facts)
  return {
    id,
    account_number: `C-0${1000 + id}`,
    address: input.address, city: 'Houston', state: 'TX', zip: input.zip,
    latitude: zipInfo.lat + ((h % 21) - 10) / 1500, longitude: zipInfo.lng + ((h % 17) - 8) / 1500,
    year_built: 1958 + (h % 52), square_footage: 1600 + (h % 1800), garage_spaces: 1 + (h % 3),
    estimated_value: value, estimated_equity: equity,
    last_sale_date: facts.last_sale_date, last_sale_price: Math.round(value - equity),
    owner_name: input.name || null, owner_occupied: true,
    contact_phone: null, contact_email: null, contact_name: input.name || null,
    contact_phone_alt: null, contact_email_alt: null, mailing_address: null,
    preferred_contact_method: null, best_time_to_call: null,
    zip_median_income: zipInfo.income, permit_count_24mo: h % 3,
    has_pool: h % 4 === 0, has_cracked_slab: false,
    lead_score: score, score_grade: grade, vertical: input.vertical,
    neighborhood_value_ratio: 1.0, neighborhood_value_pctile: 0.5, neighborhood_value_basis: 'zip',
    hcad_neighborhood_code: null, hcad_neighborhood_name: NEIGHBORHOODS[input.zip] ?? null,
    assigned_to: null, lead_source: 'manual',
    status: 'new', estimated_job_value: input.jobValue || null,
    stage_moved_at: new Date().toISOString(),
    score_updated_at: new Date().toISOString(),
    created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    archived_at: null,
  }
}

/* ── Derivations the demo page recomputes from live state ── */

export function toPipelineCard(l: Lead): PipelineCardLead {
  return {
    id: l.id, address: l.address, owner_name: l.owner_name, contact_name: l.contact_name,
    contact_phone: l.contact_phone, lead_score: l.lead_score, score_grade: l.score_grade,
    estimated_job_value: l.estimated_job_value, status: l.status, vertical: l.vertical,
    zip: l.zip, stage_moved_at: l.stage_moved_at,
  }
}

/** Board columns: every stage, cards sorted highest score first. */
export function groupByStage(leads: Lead[]): Record<string, PipelineCardLead[]> {
  const groups: Record<string, PipelineCardLead[]> = {}
  for (const stage of DEMO_STAGES) groups[stage.key] = []
  for (const l of leads) {
    const key = canonicalStage(l.status)
    if (groups[key]) groups[key].push(toPipelineCard(l))
  }
  for (const key of Object.keys(groups)) {
    groups[key].sort((a, b) => (b.lead_score ?? 0) - (a.lead_score ?? 0))
  }
  return groups
}

export function stageStats(leads: Lead[]): Record<string, { count: number; total_value: number }> {
  const stats: Record<string, { count: number; total_value: number }> = {}
  for (const stage of DEMO_STAGES) stats[stage.key] = { count: 0, total_value: 0 }
  for (const l of leads) {
    const s = stats[canonicalStage(l.status)]
    if (!s) continue
    s.count += 1
    s.total_value += l.estimated_job_value ?? 0
  }
  return stats
}

/** Weighted forecast over the open stages — same math the product shows. */
export function computeForecast(leads: Lead[]): ForecastData {
  const by_stage = OPEN_STAGES.map(stage => {
    const inStage = leads.filter(l => l.status === stage)
    const raw_value = inStage.reduce((s, l) => s + (l.estimated_job_value ?? 0), 0)
    const weight_pct = STAGE_WEIGHTS[stage] ?? 0
    return {
      stage, count: inStage.length, raw_value, weight_pct,
      weighted_value: Math.round(raw_value * weight_pct / 100),
    }
  })
  return {
    weighted_total: by_stage.reduce((s, r) => s + r.weighted_value, 0),
    by_stage,
  }
}

/** Raw open-pipeline value (the hero number). */
export function openPipelineValue(leads: Lead[]): number {
  return leads
    .filter(l => OPEN_STAGES.includes(l.status))
    .reduce((s, l) => s + (l.estimated_job_value ?? 0), 0)
}

export function winStats(leads: Lead[]): { won: number; lost: number; wonValue: number; ratePct: number | null } {
  const won = leads.filter(l => canonicalStage(l.status) === 'won')
  const lost = leads.filter(l => l.status === 'lost')
  const closed = won.length + lost.length
  return {
    won: won.length,
    lost: lost.length,
    wonValue: won.reduce((s, l) => s + (l.estimated_job_value ?? 0), 0),
    ratePct: closed === 0 ? null : Math.round((won.length / closed) * 100),
  }
}

/* ── Static dressing (not lead-derived): revenue history for the chart ── */

export interface DemoMonth { monthOffset: number; revenue: number; expenses: number }

/** Six months of P&L ending this month; labels resolve at render time. */
export const DEMO_PNL: DemoMonth[] = [
  { monthOffset: 5, revenue: 18_200, expenses: 6_400 },
  { monthOffset: 4, revenue: 22_100, expenses: 8_900 },
  { monthOffset: 3, revenue: 19_800, expenses: 7_200 },
  { monthOffset: 2, revenue: 28_400, expenses: 9_100 },
  { monthOffset: 1, revenue: 34_200, expenses: 11_600 },
  { monthOffset: 0, revenue: 21_400, expenses: 6_800 },
]

export const DEMO_OVERDUE_INVOICES = { count: 2, total: 9_450 }

/* ── Activity feed ── */

export type DemoActivityKind = 'lead' | 'move' | 'invoice' | 'task' | 'payment'

export interface DemoActivityItem {
  kind: DemoActivityKind
  title: string
  detail: string
  time: string
}

/** What the workspace was doing before the visitor arrived. Live actions the
 *  visitor takes are prepended to this in page state. */
export const SEED_ACTIVITY: DemoActivityItem[] = [
  { kind: 'move',    title: 'James Mitchell',    detail: 'Lead moved to qualified',            time: '2h ago' },
  { kind: 'invoice', title: 'Invoice #INV-042',  detail: 'Patricia Nguyen · $6,200 · sent',    time: '5h ago' },
  { kind: 'task',    title: 'Follow up on quote', detail: 'Completed',                          time: '1d ago' },
  { kind: 'payment', title: 'Invoice #INV-038',  detail: 'Gloria Hansen · $9,800 · paid',      time: '2d ago' },
  { kind: 'lead',    title: 'Maria Lopez',        detail: 'Lead added from CSV import',         time: '3d ago' },
]
