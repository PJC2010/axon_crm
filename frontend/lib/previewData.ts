// Static fixtures for the no-login dev preview (/preview/dev). These let the
// real product components render in isolation without an API call or a session,
// so UI changes to lead cards, drawers, and the "why this score" card can be
// eyeballed on any device by just opening a URL.
import type { Lead, PipelineCardLead, ScoreExplanation, Category } from './types'

export const PREVIEW_CATEGORIES: Category[] = [
  { value: 'hvac', label: 'HVAC' },
  { value: 'epoxy', label: 'Epoxy' },
  { value: 'pool', label: 'Pool' },
  { value: 'solar', label: 'Solar' },
]

export const PREVIEW_LEADS: Lead[] = [
  {
    id: 1, account_number: 'C-01001', address: '1842 Westheimer Rd', city: 'Houston', state: 'TX', zip: '77006',
    latitude: null, longitude: null, year_built: 1987, square_footage: 3400, garage_spaces: 2,
    estimated_value: 425000, estimated_equity: 180000, last_sale_date: '2015-06-12', last_sale_price: 310000,
    owner_name: 'James Mitchell', owner_occupied: true, contact_phone: '(713) 555-0142', contact_email: 'jmitchell@example.com',
    contact_name: 'James Mitchell', contact_phone_alt: null, contact_email_alt: null, mailing_address: null,
    preferred_contact_method: null, best_time_to_call: null, zip_median_income: 78500, permit_count_24mo: 0,
    has_pool: true, has_cracked_slab: false, lead_score: 94, score_grade: 'A', vertical: 'hvac',
    neighborhood_value_ratio: 1.15, neighborhood_value_pctile: 0.82, neighborhood_value_basis: 'cell',
    hcad_neighborhood_code: '5412.02', hcad_neighborhood_name: 'WESTHEIMER OAKS', assigned_to: null, lead_source: 'hcad',
    status: 'qualified', estimated_job_value: 12500, stage_moved_at: '2026-06-05T10:00:00Z',
    score_updated_at: '2026-06-01T08:00:00Z', created_at: '2026-05-28T10:00:00Z', updated_at: '2026-06-05T10:00:00Z', archived_at: null,
  },
  {
    id: 2, account_number: 'C-01002', address: '504 River Oaks Blvd', city: 'Houston', state: 'TX', zip: '77019',
    latitude: null, longitude: null, year_built: 1992, square_footage: 4200, garage_spaces: 3,
    estimated_value: 680000, estimated_equity: 320000, last_sale_date: '2018-03-22', last_sale_price: 520000,
    owner_name: 'Patricia Nguyen', owner_occupied: true, contact_phone: '(713) 555-0287', contact_email: 'pnguyen@example.com',
    contact_name: 'Patricia Nguyen', contact_phone_alt: null, contact_email_alt: null, mailing_address: null,
    preferred_contact_method: null, best_time_to_call: null, zip_median_income: 125000, permit_count_24mo: 1,
    has_pool: false, has_cracked_slab: false, lead_score: 88, score_grade: 'A', vertical: 'epoxy',
    neighborhood_value_ratio: 1.40, neighborhood_value_pctile: 0.95, neighborhood_value_basis: 'cell',
    hcad_neighborhood_code: '4521.00', hcad_neighborhood_name: 'RIVER OAKS SEC 1-3', assigned_to: null, lead_source: 'rentcast',
    status: 'quote_sent', estimated_job_value: 6200, stage_moved_at: '2026-06-02T14:00:00Z',
    score_updated_at: '2026-06-01T08:00:00Z', created_at: '2026-05-20T10:00:00Z', updated_at: '2026-06-02T14:00:00Z', archived_at: null,
  },
  {
    id: 4, account_number: 'C-01004', address: '7614 Bissonnet St', city: 'Houston', state: 'TX', zip: '77074',
    latitude: null, longitude: null, year_built: 1968, square_footage: 1850, garage_spaces: 1,
    estimated_value: 220000, estimated_equity: 140000, last_sale_date: '2008-11-04', last_sale_price: 145000,
    owner_name: 'Maria Lopez', owner_occupied: true, contact_phone: '(832) 555-0198', contact_email: null,
    contact_name: 'Maria Lopez', contact_phone_alt: null, contact_email_alt: null, mailing_address: null,
    preferred_contact_method: null, best_time_to_call: null, zip_median_income: 52000, permit_count_24mo: 2,
    has_pool: false, has_cracked_slab: true, lead_score: 76, score_grade: 'B', vertical: 'pool',
    neighborhood_value_ratio: 1.05, neighborhood_value_pctile: 0.60, neighborhood_value_basis: 'zip',
    hcad_neighborhood_code: null, hcad_neighborhood_name: null, assigned_to: null, lead_source: 'csv_import',
    status: 'new', estimated_job_value: 4800, stage_moved_at: null,
    score_updated_at: '2026-06-01T08:00:00Z', created_at: '2026-06-07T10:00:00Z', updated_at: '2026-06-07T10:00:00Z', archived_at: null,
  },
  {
    id: 5, account_number: 'C-01005', address: '3310 Montrose Blvd', city: 'Houston', state: 'TX', zip: '77006',
    latitude: null, longitude: null, year_built: 2001, square_footage: 2800, garage_spaces: 2,
    estimated_value: 510000, estimated_equity: 250000, last_sale_date: '2019-07-15', last_sale_price: 420000,
    owner_name: 'David Park', owner_occupied: true, contact_phone: '(713) 555-0331', contact_email: 'dpark@example.com',
    contact_name: 'David Park', contact_phone_alt: null, contact_email_alt: null, mailing_address: null,
    preferred_contact_method: null, best_time_to_call: null, zip_median_income: 78500, permit_count_24mo: 0,
    has_pool: true, has_cracked_slab: false, lead_score: 61, score_grade: 'C', vertical: 'solar',
    neighborhood_value_ratio: 1.25, neighborhood_value_pctile: 0.88, neighborhood_value_basis: 'cell',
    hcad_neighborhood_code: '5412.05', hcad_neighborhood_name: 'MONTROSE', assigned_to: null, lead_source: 'rentcast',
    status: 'contacted', estimated_job_value: 18000, stage_moved_at: null,
    score_updated_at: '2026-06-01T08:00:00Z', created_at: '2026-06-06T10:00:00Z', updated_at: '2026-06-06T10:00:00Z', archived_at: null,
  },
]

export const PREVIEW_PIPELINE_CARD: PipelineCardLead = {
  id: 1, address: '1842 Westheimer Rd', owner_name: 'James Mitchell', contact_name: 'James Mitchell',
  contact_phone: '(713) 555-0142', lead_score: 94, score_grade: 'A', estimated_job_value: 12500,
  status: 'qualified', vertical: 'hvac', zip: '77006', stage_moved_at: null,
}

export const PREVIEW_EXPLANATION: ScoreExplanation = {
  lead_id: 1,
  score: 94,
  grade: 'A',
  vertical: 'hvac',
  is_default_profile: false,
  summary: 'A long-time owner with strong home equity in a high-value neighborhood — a prime candidate for a system upgrade.',
  top_drivers: ['equity', 'sale_recency', 'home_value'],
  factors: [
    { key: 'equity', label: 'Home equity', description: 'Owners with more equity can more easily fund a big-ticket job.', weight: 0.30, signal: 0.9, contribution: 27.0 },
    { key: 'sale_recency', label: 'Years in home', description: 'Bought in 2015 — long-tenured owners replace aging systems more often.', weight: 0.25, signal: 0.85, contribution: 21.3 },
    { key: 'home_value', label: 'Home value', description: 'A $425K home in a top-quartile area signals budget for premium work.', weight: 0.20, signal: 0.82, contribution: 16.4 },
    { key: 'owner_occupied', label: 'Owner occupied', description: 'The owner lives here, so they decide and pay for the work directly.', weight: 0.15, signal: 1.0, contribution: 15.0 },
    { key: 'area_income', label: 'Area income', description: 'Median household income of $78.5K supports the estimated job value.', weight: 0.10, signal: 0.7, contribution: 7.0 },
  ],
  vertical_description: [
    { key: 'equity', label: 'Home equity', description: 'Ability to fund the job', weight: 0.30 },
    { key: 'sale_recency', label: 'Years in home', description: 'Time since purchase', weight: 0.25 },
    { key: 'home_value', label: 'Home value', description: 'Property value', weight: 0.20 },
  ],
  score_updated_at: '2026-06-01T08:00:00Z',
  weights_drift: false,
}
