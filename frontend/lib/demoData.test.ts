import { describe, expect, it } from 'vitest'
import {
  DEMO_FACTORS, DEMO_STAGES, OPEN_STAGES, STAGE_WEIGHTS,
  buildDemoExplanation, computeForecast, groupByStage, makeDemoLeads,
  makeVisitorLead, openPipelineValue, scoreDemoLead, stageStats, winStats,
} from './demoData'

describe('demo scoring model', () => {
  it('factor weights sum to 1.0', () => {
    const total = DEMO_FACTORS.reduce((s, f) => s + f.weight, 0)
    expect(total).toBeCloseTo(1.0, 10)
  })

  it('scores stay in 0–100 and map to a valid grade', () => {
    const extremes = [
      { estimated_value: 0, estimated_equity: 0, last_sale_date: null, owner_occupied: false, zip_median_income: 0 },
      { estimated_value: 5_000_000, estimated_equity: 5_000_000, last_sale_date: '1980-01-01', owner_occupied: true, zip_median_income: 500_000 },
    ]
    for (const facts of extremes) {
      const { score, grade } = scoreDemoLead(facts)
      expect(score).toBeGreaterThanOrEqual(0)
      expect(score).toBeLessThanOrEqual(100)
      expect(['A', 'B', 'C', 'D']).toContain(grade)
    }
  })
})

describe('makeDemoLeads', () => {
  const leads = makeDemoLeads()

  it('every lead sits in a known stage', () => {
    const keys = new Set(DEMO_STAGES.map(s => s.key))
    for (const l of leads) expect(keys.has(l.status)).toBe(true)
  })

  it('stored grade agrees with the scoring model', () => {
    for (const l of leads) {
      const { score, grade } = scoreDemoLead({
        estimated_value: l.estimated_value ?? 0,
        estimated_equity: l.estimated_equity ?? 0,
        last_sale_date: l.last_sale_date,
        owner_occupied: l.owner_occupied ?? false,
        zip_median_income: l.zip_median_income ?? 0,
      })
      expect(l.lead_score).toBe(score)
      expect(l.score_grade).toBe(grade)
    }
  })

  it('has leads spread over more than three stages and more than one grade', () => {
    expect(new Set(leads.map(l => l.status)).size).toBeGreaterThan(3)
    expect(new Set(leads.map(l => l.score_grade)).size).toBeGreaterThan(1)
  })

  it('every lead has coordinates for the demo map', () => {
    for (const l of leads) {
      expect(l.latitude).toBeTypeOf('number')
      expect(l.longitude).toBeTypeOf('number')
    }
  })
})

describe('derivations', () => {
  const leads = makeDemoLeads()

  it('forecast covers exactly the open stages with weighted math', () => {
    const f = computeForecast(leads)
    expect(f.by_stage.map(r => r.stage)).toEqual(OPEN_STAGES)
    for (const row of f.by_stage) {
      expect(row.weighted_value).toBe(Math.round(row.raw_value * STAGE_WEIGHTS[row.stage] / 100))
    }
    expect(f.weighted_total).toBe(f.by_stage.reduce((s, r) => s + r.weighted_value, 0))
  })

  it('stage stats count every lead exactly once', () => {
    const stats = stageStats(leads)
    const counted = Object.values(stats).reduce((s, r) => s + r.count, 0)
    expect(counted).toBe(leads.length)
  })

  it('open pipeline value only counts open stages', () => {
    const open = leads.filter(l => OPEN_STAGES.includes(l.status))
    expect(openPipelineValue(leads)).toBe(open.reduce((s, l) => s + (l.estimated_job_value ?? 0), 0))
  })

  it('board groups sort by score, highest first', () => {
    const groups = groupByStage(leads)
    for (const cards of Object.values(groups)) {
      for (let i = 1; i < cards.length; i++) {
        expect(cards[i - 1].lead_score ?? 0).toBeGreaterThanOrEqual(cards[i].lead_score ?? 0)
      }
    }
  })

  it('win stats derive rate from closed deals only', () => {
    const { won, lost, ratePct } = winStats(leads)
    expect(won + lost).toBeGreaterThan(0)
    expect(ratePct).toBe(Math.round((won / (won + lost)) * 100))
  })
})

describe('status vocabulary', () => {
  it("folds 'converted' into the won bucket everywhere leads are bucketed", () => {
    const leads = makeDemoLeads().map(l =>
      l.status === 'won' ? { ...l, status: 'converted' as const } : l)
    const groups = groupByStage(leads)
    const stats = stageStats(leads)
    expect(groups.won.length).toBeGreaterThan(0)
    expect(stats.won.count).toBe(groups.won.length)
    expect(winStats(leads).won).toBe(groups.won.length)
    const counted = Object.values(stats).reduce((s, r) => s + r.count, 0)
    expect(counted).toBe(leads.length)
  })

  it("carries a 'not_interested' column like the product's fallback board", () => {
    expect(DEMO_STAGES.some(s => s.key === 'not_interested')).toBe(true)
    const leads = makeDemoLeads().map((l, i) =>
      i === 0 ? { ...l, status: 'not_interested' as const } : l)
    expect(groupByStage(leads).not_interested.length).toBe(1)
  })
})

describe('buildDemoExplanation', () => {
  const lead = makeDemoLeads()[0]
  const exp = buildDemoExplanation(lead)

  it('factor contributions add back up to the lead score', () => {
    const total = exp.factors.reduce((s, f) => s + f.contribution, 0)
    expect(Math.abs(total - (lead.lead_score ?? 0))).toBeLessThanOrEqual(0.5)
  })

  it('top drivers reference real factors', () => {
    const keys = new Set(exp.factors.map(f => f.key))
    expect(exp.top_drivers.length).toBe(3)
    for (const k of exp.top_drivers) expect(keys.has(k)).toBe(true)
  })
})

describe('makeVisitorLead', () => {
  const input = { name: 'Dana Fox', address: '42 Demo Ln', zip: '77008', vertical: 'roofing', jobValue: 9000 }

  it('is deterministic for the same input', () => {
    const a = makeVisitorLead(101, input)
    const b = makeVisitorLead(101, input)
    expect(a.lead_score).toBe(b.lead_score)
    expect(a.estimated_value).toBe(b.estimated_value)
    expect(a.estimated_equity).toBe(b.estimated_equity)
  })

  it('produces a coherent scored lead in the new stage', () => {
    const l = makeVisitorLead(102, input)
    expect(l.status).toBe('new')
    const { score, grade } = scoreDemoLead({
      estimated_value: l.estimated_value ?? 0,
      estimated_equity: l.estimated_equity ?? 0,
      last_sale_date: l.last_sale_date,
      owner_occupied: true,
      zip_median_income: l.zip_median_income ?? 0,
    })
    expect(l.lead_score).toBe(score)
    expect(l.score_grade).toBe(grade)
    expect(l.latitude).toBeTypeOf('number')
    expect(l.longitude).toBeTypeOf('number')
  })

  it('falls back to a known ZIP when given an unknown one', () => {
    const l = makeVisitorLead(103, { ...input, zip: '00000' })
    expect(l.zip_median_income).toBeGreaterThan(0)
    expect(l.latitude).toBeTypeOf('number')
  })
})
