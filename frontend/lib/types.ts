export type LeadStatus = 'new' | 'contacted' | 'qualified' | 'not_interested' | 'converted' | 'quote_sent' | 'won' | 'lost'
export type ScoreGrade = 'A' | 'B' | 'C' | 'D'
export type TaskPriority = 'low' | 'normal' | 'high' | 'urgent'

export interface Lead {
  id: number
  account_number: string | null
  address: string | null
  city: string | null
  state: string | null
  zip: string | null
  latitude: number | null
  longitude: number | null
  year_built: number | null
  square_footage: number | null
  garage_spaces: number | null
  estimated_value: number | null
  estimated_equity: number | null
  last_sale_date: string | null
  last_sale_price: number | null
  owner_name: string | null
  owner_occupied: boolean | null
  contact_phone: string | null
  contact_email: string | null
  contact_name: string | null
  contact_phone_alt: string | null
  contact_email_alt: string | null
  mailing_address: string | null
  preferred_contact_method: string | null
  best_time_to_call: string | null
  // Lead-level DNC flag: set by the dialer's do_not_call disposition, enforced
  // by the dialer queue; clearable via the contact PATCH (owner undo path).
  do_not_call?: boolean
  zip_median_income: number | null
  permit_count_24mo: number | null
  has_pool: boolean | null
  has_cracked_slab: boolean | null
  lead_score: number | null
  score_grade: ScoreGrade | null
  vertical: string | null
  neighborhood_value_ratio: number | null
  neighborhood_value_pctile: number | null
  neighborhood_value_basis: string | null
  hcad_neighborhood_code: string | null
  hcad_neighborhood_name: string | null
  status: LeadStatus
  assigned_to: number | null
  lead_source: string | null
  estimated_job_value: number | null
  stage_moved_at: string | null
  score_updated_at: string | null
  created_at: string | null
  updated_at: string | null
  archived_at: string | null
  // Geo layer (juncto geo layer): standalone location score, the blend of it with
  // the property score, and the component breakdown. Populated once geo-scored.
  geo_score?: number | null
  final_score?: number | null
  geo_components?: GeoComponents | null
  nearest_customer_m?: number | null
  customers_within_1600m?: number | null
  // Account-defined custom field values, keyed by RecordFieldDef.key.
  custom_fields?: Record<string, unknown>
  // True when this row is hidden behind the monthly scored-lead allowance
  // (api/scoring_quota.py): address partially masked, identity/contact nulled.
  quota_masked?: boolean
}

// The geo score's explainable breakdown (stored as JSONB, surfaced on the lead).
export interface GeoComponents {
  proximity: number
  density: number
  neighbor: number
  territory_gate: number
  event_bonus?: number
  event?: { type: string; id: number; name: string | null } | null
  inside_service_area?: boolean
  route_weight?: number
  neighbor_weight?: number
  geo_blend?: number
}

// Account-defined custom field (the generic record-model layer; see
// api/routes/record_fields.py).
export type RecordFieldType = 'text' | 'number' | 'date' | 'boolean' | 'select'

export interface RecordFieldDef {
  id: number
  key: string
  label: string
  field_type: RecordFieldType
  options: string[]
  sort_order: number
}

// Monthly scored-lead reveal allowance state for metered plans.
export interface ScoringQuota {
  limit: number
  used: number
  remaining: number
}

export interface LeadPage {
  total: number
  page: number
  page_size: number
  results: Lead[]
  // Present only for metered plans; null/absent means unlimited.
  scoring_quota?: ScoringQuota | null
}

export interface CustomerSearchResult {
  id: number
  account_number: string | null
  contact_name: string | null
  owner_name: string | null
  address: string | null
  city: string | null
  zip: string | null
  contact_phone: string | null
  status: LeadStatus
  score_grade: ScoreGrade | null
}

// ── Property map ──────────────────────────────────────────────────────────────
// A geohash-6 'block' aggregate for the service-area choropleth. Carries both
// color bases (recent intent signals + score) so the signals/score toggle on the
// map never needs to refetch. The cell rectangle is derived client-side by
// decoding `cell`.
export interface MapCell {
  cell: string
  name: string | null
  leads: number
  avg_score: number | null
  grade_a: number
  grade_b: number
  grade_c: number
  grade_d: number
  signal_count: number
  lat: number | null
  lng: number | null
}

// A single property pin — lighter than Lead for bulk viewport payloads.
export interface MapPoint {
  id: number
  address: string | null
  latitude: number
  longitude: number
  lead_score: number | null
  score_grade: ScoreGrade | null
  status: LeadStatus
  signals: string[]
}

export interface MapBounds {
  min_lat: number
  min_lng: number
  max_lat: number
  max_lng: number
}

export interface MapFilters {
  vertical?: string
  status?: string
  signal_days?: number
}

// A ZIP the account holds leads in, with the extent of those leads. Backs the
// map's ZIP jump control, which fits straight to this box.
export interface MapZip extends MapBounds {
  zip: string
  leads: number
}

// ── Geo layer (Phase 2–3) ──────────────────────────────────────────────────────

export type HeatmapMetric = 'density' | 'avg_score'

export interface HeatmapCell {
  h3: string
  value: number | null            // customers (density) or avg score, per metric
  leads: number
  customers: number
  avg_score: number | null
  boundary: [number, number][] | null  // ring of [lng, lat] for the hex outline
  center: [number, number] | null      // [lat, lng]
}

export interface HeatmapResponse {
  metric: HeatmapMetric
  resolution: number
  available: boolean              // false when h3 isn't installed / no cells yet
  cells: HeatmapCell[]
}

// GeoJSON-ish cluster feature collection (hulls). geometry is null for a cluster
// too small to form a polygon.
export interface ClusterFeature {
  type: 'Feature'
  geometry: { type: 'Polygon'; coordinates: number[][][] } | null
  properties: {
    cluster_label: number
    customer_count: number
    centroid: [number, number]    // [lng, lat]
    computed_at: string | null
  }
}
export interface ClusterCollection {
  type: 'FeatureCollection'
  features: ClusterFeature[]
}

export interface ProspectSeed {
  cluster_id?: number
  customer_id?: number
  lat?: number
  lng?: number
}
export interface ProspectResult {
  status: string
  seed_type?: string
  center?: [number, number]
  h3?: string | null
  records_returned?: number
  after_refine?: number
  after_dedupe?: number
  ingested?: number
  scored?: number
  api_requests?: number
}

export interface NeighborHit {
  id: number
  address: string | null
  zip: string | null
  latitude: number
  longitude: number
  status: LeadStatus
  score_grade: ScoreGrade | null
  vertical: string | null
  final_score: number | null
  distance_m: number
}
export interface BlastRadiusResult {
  job_id: number
  radius_m: number
  count: number
  neighbors: NeighborHit[]
}

export interface ServiceArea {
  polygon: { type: 'Polygon'; coordinates: number[][][] } | null
  source: string | null
}

// Event layer (Phase 4): polygons whose leads get a scoring bonus.
export interface EventFeature {
  type: 'Feature'
  geometry: { type: 'Polygon'; coordinates: number[][][] } | null
  properties: {
    id: number
    event_type: string
    name: string | null
    bonus: number | null
    starts_at: string | null
    ends_at: string | null
    active: boolean
  }
}
export interface EventCollection {
  type: 'FeatureCollection'
  features: EventFeature[]
}
export interface EventCreate {
  event_type: string
  name?: string
  polygon: object
  bonus?: number
  starts_at?: string
  ends_at?: string
  metadata?: Record<string, unknown>
}

export interface ScoreFactor {
  key: string
  label: string
  description: string
  weight: number
  signal: number
  contribution: number
}

export interface VerticalFactor {
  key: string
  label: string
  description: string
  weight: number
}

export interface ScoreExplanation {
  lead_id: number
  score: number | null
  grade: ScoreGrade | null
  vertical: string | null
  is_default_profile: boolean
  factors: ScoreFactor[]
  top_drivers: string[]
  summary: string | null
  vertical_description: VerticalFactor[]
  score_updated_at: string | null
  weights_drift: boolean
}

export interface Note {
  id: number
  property_id: number
  note: string
  created_at: string
}

export interface HistoryEntry {
  id: number
  property_id: number
  action: string
  outcome: string | null
  created_at: string
  // Two-way messaging: null on legacy rows and manual log entries.
  channel?: 'sms' | 'email' | null
  direction?: 'inbound' | 'outbound' | null
  body?: string | null
}

// Scoring feedback loop: append-only outcome events. Most fire automatically
// server-side from actions the user already takes (list render -> surfaced,
// detail open -> viewed, stage changes -> contacted/quote_sent/won/lost). Only
// 'disqualified' is raised explicitly, via the "Bad lead" action.
export type LeadEventType =
  | 'surfaced' | 'viewed' | 'contact_attempted' | 'contacted'
  | 'quote_sent' | 'won' | 'lost' | 'disqualified' | 'suppressed'

export interface LeadEventCreate {
  event_type: LeadEventType
  channel?: string | null
  metadata?: Record<string, unknown> | null
}

export interface LeadEvent {
  id: number
  property_id: number
  account_id: number
  event_type: LeadEventType
  channel: string | null
  actor_user_id: number | null
  occurred_at: string
  metadata: Record<string, unknown> | null
}

export interface TimelineEntry {
  id: number
  property_id: number
  type: 'history' | 'note' | 'task' | 'signal'
  title: string
  detail: string | null
  created_at: string
  // Present on 'history' entries that are messages; renders as a chat bubble.
  channel?: 'sms' | 'email' | null
  direction?: 'inbound' | 'outbound' | null
  body?: string | null
}

export interface LeadFilters {
  zip?: string
  grade?: string
  vertical?: string
  status?: string
  min_value?: number
  max_value?: number
  neighborhood?: string
  min_neighborhood_pctile?: number
  sort?: string
  page?: number
  page_size?: number
}

export interface Neighborhood {
  cell: string
  name: string | null
  leads: number
  median_value: number | null
}

export interface Task {
  id: number
  property_id: number | null
  assigned_to: number | null
  title: string
  due_date: string | null
  priority: TaskPriority
  is_complete: boolean
  completed_at: string | null
  created_by: number | null
  created_at: string
  updated_at: string
}

export interface TaskCreate {
  property_id?: number
  title: string
  due_date?: string
  priority?: TaskPriority
  assigned_to?: number
}

// ── Contact / lead import ──────────────────────────────────────────────────────

export interface ImportPreview {
  headers: string[]
  target_fields: string[]
  mapping: Record<string, string>   // csv header -> field
  total_rows: number
  usable_rows: number
  skip_rows: number
  sample: Record<string, string | number>[]
}

export interface ImportResult {
  imported: number
  updated: number
  skipped: number
  coerced_statuses?: number   // rows whose status wasn't one of this account's stages
  error_count?: number        // total failed rows; errors[] is capped server-side
  errors: string[]
}

export interface PipelineCardLead {
  id: number
  address: string | null
  owner_name: string | null
  contact_name: string | null
  contact_phone: string | null
  lead_score: number | null
  score_grade: ScoreGrade | null
  estimated_job_value: number | null
  status: LeadStatus
  vertical: string | null
  zip: string | null
  /** When the lead last changed stage — drives the cooling indicator. */
  stage_moved_at: string | null
}

export type PipelineGroup = Record<string, PipelineCardLead[]>

export interface PipelineCounts {
  today: number
  overdue: number
}

// Optional, gateable feature modules. Mirrors api/entitlements.py MODULE_KEYS.
export type ModuleKey =
  | 'prospecting'
  | 'map'
  | 'invoicing'
  | 'bookkeeping'
  | 'quotes'
  | 'automation'
  | 'policies'
  | 'orders'
  | 'appointments'
  | 'calls'

export type ModuleMap = Record<ModuleKey, boolean>

// ── Call tracking (the `calls` module) ────────────────────────────────────────

// The account's Twilio tracking number, as returned by GET /calls/settings.
export interface TrackingNumber {
  id: number
  phone_number: string
  friendly_name: string | null
  forward_to: string | null
  created_at: string
}

// The missed-call auto-text: an SMS template plus the `call_event` workflow rule
// that sends it. `enabled` is the rule's is_active flag — turning it off keeps
// the wording, so switching it back on restores whatever the owner wrote.
export interface AutoReplySettings {
  enabled: boolean
  rule_id: number | null
  template_id: number | null
  body: string | null
}

export interface CallSettings {
  configured: boolean
  // Browser calling (the power dialer) — needs the TWILIO_API_KEY_* / TwiML
  // App env vars on top of `configured`; false = the dialer uses tel: links.
  voice_dialing: boolean
  number: TrackingNumber | null
  auto_reply: AutoReplySettings
}

// What POST /calls/activate and PATCH /calls/settings return — the same number
// + auto-reply pair as CallSettings, minus the server-capability flag.
export interface CallSettingsResponse {
  ok: boolean
  number: TrackingNumber | null
  auto_reply: AutoReplySettings
}

export interface AvailableNumber {
  phone_number: string
  friendly_name: string
  locality: string | null
  region: string | null
}

// Inbound calls resolve to answered/missed/busy; outbound (dialer) calls use
// Twilio's finer DialCallStatus vocabulary. Mirrors the calls.outcome CHECK.
export type CallOutcome = 'answered' | 'missed' | 'busy' | 'no_answer' | 'failed' | 'canceled'

// The rep's verdict after a dialer call — separate from the mechanical outcome.
export type CallDisposition =
  | 'no_answer'
  | 'voicemail'
  | 'interested'
  | 'not_interested'
  | 'callback'
  | 'wrong_number'
  | 'do_not_call'

export interface CallLogEntry {
  id: number
  property_id: number | null
  direction: 'inbound' | 'outbound'
  from_number: string | null
  from_digits: string | null
  to_number: string | null
  caller_name: string | null
  status: 'in-progress' | 'completed'
  outcome: CallOutcome | null
  disposition: CallDisposition | null
  duration_seconds: number | null
  lead_created: boolean
  started_at: string
  contact_name: string | null
}

export interface CallLogPage {
  items: CallLogEntry[]
  total: number
}

// ── Power dialer (the `calls` module's outbound half) ────────────────────────

// One callable lead in the queue, A-grade first, best score first.
export interface DialerQueueItem {
  id: number
  contact_name: string | null
  owner_name: string | null
  address: string | null
  city: string | null
  zip: string | null
  contact_phone: string | null
  contact_phone_alt: string | null
  contact_email: string | null
  best_time_to_call: string | null
  preferred_contact_method: string | null
  vertical: string | null
  status: LeadStatus
  lead_score: number | null
  score_grade: ScoreGrade | null
  estimated_job_value: number | null
  last_call_at: string | null
  last_disposition: CallDisposition | null
  last_outcome: CallOutcome | null
}

export interface DialerQueueResponse {
  items: DialerQueueItem[]
  total: number
  // Leads hidden behind the monthly scored-lead allowance — dropped from the
  // queue (their phones are withheld), reported so the UI can say so.
  masked_count: number
  scoring_quota?: ScoringQuota | null
  stats: { calls_today: number; connects_today: number }
  voice_dialing: boolean
}

export interface DialerTokenResponse {
  token: string
  identity: string
  ttl_seconds: number
}

export interface DispositionResult {
  ok: boolean
  call_id: number
  disposition: CallDisposition
  lead_status: LeadStatus
  do_not_call: boolean
  task_id: number | null
}

// A category option ("vertical" in home-services terms). Driven by business type.
export interface Category {
  value: string
  label: string
}

export interface AccountFeatures {
  plan_name: string
  modules: ModuleMap
  // Monthly scored-lead allowance for metered plans; null/absent = unlimited.
  scoring_quota?: ScoringQuota | null
  // Business-type profile (see api/business_types.py). Optional so older payloads
  // / pre-load states degrade gracefully to home-services defaults.
  business_type?: string
  property_based?: boolean
  terminology?: Record<string, string>
  categories?: Category[]
  // Dashboard KPI tile ids + child objects for this business type (Phase 6).
  kpis?: string[]
  objects?: string[]
  // Ordered lead-list column keys (see frontend/components/lead/leadColumns.tsx).
  list_columns?: string[]
}

export interface BusinessTypeInfo {
  key: string
  label: string
  property_based: boolean
}

// Aggregates from GET /api/objects/kpis; keys present only when the matching
// module is enabled for the account.
export interface ObjectKpis {
  premium_in_force?: number
  active_policies?: number
  renewals_30d?: number
  revenue_mtd?: number
  orders_30d?: number
  repeat_rate?: number | null
  appointments_7d?: number
}

export interface User {
  id: number
  username: string
  email: string
  role: string
  is_active: boolean
  // The org this user belongs to. /auth/me has always returned it (UserOut);
  // the admin danger zone is the first caller that needs to read it.
  account_id: number
  onboarding_complete: boolean
  // Whether the login email has been confirmed (self-serve signups verify via
  // an emailed link; admin-created and OAuth users arrive verified).
  email_verified?: boolean
  // Whether the user opted in to SMS from Axon (account + territory alerts).
  // Recorded with timestamp + source for A2P 10DLC; toggled in Settings.
  sms_consent?: boolean
  // Populated by GET /auth/me; enabled feature modules for this user's account.
  modules?: Partial<ModuleMap>
  business_type?: string
  // Cross-tenant /api/admin access (platform operator, not a tenant role).
  // Populated by GET /auth/me; drives the Admin nav link and AdminGuard.
  is_platform_admin?: boolean
}

export interface ChecklistStatus {
  has_leads: boolean
  has_contact: boolean
  has_invoice: boolean
  has_workflow: boolean
  has_expense: boolean
}

export interface PipelineSchedule {
  id: number
  zip: string
  vertical: string | null
  day_of_week: string
  hour: number
  is_active: boolean
  top_n: number | null
  center_address: string | null
  radius_mi: number | null
  created_at: string
}

export interface PipelineRun {
  id: number
  schedule_id: number | null
  zip: string
  vertical: string | null
  status: 'queued' | 'running' | 'done' | 'failed'
  triggered_by: string
  top_n: number | null
  center_address: string | null
  radius_mi: number | null
  started_at: string | null
  finished_at: string | null
  result_json: Record<string, unknown> | null
  created_at: string
}

// ── Expenses ──────────────────────────────────────────────────────────────────

export type ExpenseCategory = 'fuel' | 'materials' | 'meals' | 'tools' | 'advertising' | 'subcontractor' | 'office' | 'other'
export type PaymentMethod = 'cash' | 'card' | 'check' | 'zelle' | 'other'

export interface Expense {
  id: number
  amount: number
  category: ExpenseCategory
  vendor: string
  description?: string | null
  expense_date: string
  payment_method: PaymentMethod
  is_tax_deductible: boolean
  property_id?: number | null
  receipt_url?: string | null
  created_by?: number | null
  created_at: string
}

export interface ExpenseCreate {
  amount: number
  category: ExpenseCategory
  vendor: string
  description?: string
  expense_date: string
  payment_method: PaymentMethod
  is_tax_deductible: boolean
  property_id?: number
}

export interface ExpenseSummary {
  total: number
  by_category: Partial<Record<ExpenseCategory, number>>
  tax_deductible_total: number
  count: number
}

// Fields extracted from a receipt photo to pre-fill the expense form. All
// optional — a partial read still pre-fills whatever was recognized.
export interface ReceiptScanResult {
  amount?: number | null
  vendor?: string | null
  expense_date?: string | null
  category?: ExpenseCategory | null
  is_tax_deductible?: boolean | null
  description?: string | null
}

export interface ExpenseFilters {
  year?: number
  month?: number
  category?: ExpenseCategory
  deductible?: boolean
  page?: number
  page_size?: number
}

// ── Bookkeeping / Invoices ────────────────────────────────────────────────────

export type InvoiceStatus = 'draft' | 'sent' | 'paid' | 'partial' | 'overdue' | 'void'

export interface LineItem {
  id?: number
  invoice_id?: number
  description: string
  quantity: number
  unit_price: number
  amount?: number
  sort_order?: number
}

export interface InvoicePayment {
  id: number
  invoice_id: number
  amount: number
  payment_date: string
  payment_method: string
  notes?: string | null
  created_by?: number | null
  created_at: string
  // Set on payments the Stripe webhook recorded; these can't be deleted
  // manually (refund via Stripe instead).
  stripe_payment_intent_id?: string | null
  stripe_charge_id?: string | null
}

export interface Invoice {
  id: number
  invoice_number: string
  property_id?: number | null
  client_name: string
  client_phone?: string | null
  client_email?: string | null
  client_address?: string | null
  status: InvoiceStatus
  subtotal: number
  tax_rate: number
  tax_amount: number
  total: number
  amount_paid: number
  balance_due: number
  issue_date: string
  due_date?: string | null
  notes?: string | null
  created_at: string
  line_items: LineItem[]
  payments: InvoicePayment[]
  // delivery tracking
  sent_at?: string | null
  sent_channels?: string[] | null
  // recurring revenue
  recurrence?: InvoiceRecurrence | null
  recurrence_next?: string | null
  recurrence_end?: string | null
  recurring_source_id?: number | null
  // Public pay-page token (/pay/{pay_token}); separate from the PDF token.
  pay_token?: string | null
}

export type InvoiceRecurrence = 'weekly' | 'monthly' | 'quarterly' | 'annual'

// ── Online payments (Stripe Connect) ─────────────────────────────────────────

export interface StripeStatus {
  available: boolean          // platform key configured on the server
  connected: boolean          // this account has a connected account
  charges_enabled: boolean
  payouts_enabled: boolean
  details_submitted: boolean
}

// ── Subscription billing (the account paying for Axon) — GET /billing ────────

export interface BillingPlan {
  plan: string                // 'starter' | 'growth' | 'pro'
  label: string
  monthly_usd: number
  blurb: string
  modules: string[]           // module keys this plan grants
  purchasable: boolean        // a Stripe price id is configured for it
}

export interface BillingInfo {
  configured: boolean         // self-serve billing available on this server
  plan_name: string           // the account's current entitlement plan
  status?: string | null      // trialing | trial_expired | active | past_due | canceled…
  trial_ends_at?: string | null
  current_period_end?: string | null
  cancel_at_period_end: boolean
  has_subscription: boolean
  plans: BillingPlan[]
}

export interface PublicPayInfo {
  business_name: string
  invoice_number: string
  status: InvoiceStatus
  total: number
  amount_paid: number
  balance_due: number
  issue_date: string
  due_date?: string | null
  payable: boolean
  pdf_url: string
}

export interface InvoiceCreate {
  property_id?: number
  client_name: string
  client_phone?: string
  client_email?: string
  client_address?: string
  tax_rate: number
  issue_date: string
  due_date?: string
  notes?: string
  line_items: { description: string; quantity: number; unit_price: number; sort_order?: number }[]
  // '' stops a series; a cadence starts/updates it.
  recurrence?: InvoiceRecurrence | ''
  recurrence_end?: string
}

export interface InvoiceFilters {
  status?: InvoiceStatus
  year?: number
  month?: number
  page?: number
  page_size?: number
}

// ── Quotes ────────────────────────────────────────────────────────────────────

export type QuoteStatus = 'draft' | 'sent' | 'accepted' | 'declined' | 'expired'

export interface QuoteLineItem {
  id?: number
  quote_id?: number
  description: string
  quantity: number
  unit_price: number
  amount?: number
  sort_order?: number
}

export interface Quote {
  id: number
  quote_number: string
  property_id?: number | null
  client_name: string
  client_phone?: string | null
  client_email?: string | null
  client_address?: string | null
  status: QuoteStatus
  subtotal: number
  tax_rate: number
  tax_amount: number
  total: number
  issue_date: string
  valid_until?: string | null
  notes?: string | null
  sent_at?: string | null
  viewed_at?: string | null
  accepted_at?: string | null
  declined_at?: string | null
  decline_reason?: string | null
  converted_invoice_id?: number | null
  public_token?: string | null
  created_at: string
  line_items: QuoteLineItem[]
}

/** Sanitized customer-facing quote served by /api/public/quotes/{token}. */
export interface PublicQuote {
  quote_number: string
  business_name: string
  client_name: string
  status: QuoteStatus
  subtotal: number
  tax_rate: number
  tax_amount: number
  total: number
  issue_date: string
  valid_until?: string | null
  notes?: string | null
  accepted_at?: string | null
  declined_at?: string | null
  line_items: { description: string; quantity: number; unit_price: number; amount: number }[]
}

export interface QuoteCreate {
  property_id?: number
  client_name: string
  client_phone?: string
  client_email?: string
  client_address?: string
  tax_rate: number
  issue_date: string
  valid_until?: string
  notes?: string
  line_items: { description: string; quantity: number; unit_price: number; sort_order?: number }[]
}

export interface QuoteFilters {
  status?: QuoteStatus
  page?: number
  page_size?: number
}

export interface ARSummary {
  total_invoiced: number
  total_collected: number
  total_outstanding: number
  total_overdue: number
  invoice_count: number
  overdue_count: number
}

export interface AgingBucket {
  label: string
  count: number
  amount: number
}

export interface PnLMonth {
  year: number
  month: number
  revenue: number
  expenses: number
  net: number
}

export interface PnLReport {
  year: number
  months: PnLMonth[]
  total_revenue: number
  total_expenses: number
  net_profit: number
}

// ── Pipeline Stages ──────────────────────────────────────────────────────

export interface PipelineStage {
  id: number
  key: string
  label: string
  color: string
  sort_order: number
  is_terminal: boolean
  is_default: boolean
  created_by: number | null
  created_at: string
}

// ── Pipeline Analytics ───────────────────────────────────────────────────────

export interface PipelineAnalytics {
  win_rate: number
  avg_cycle_time: number | null
  leads_won: number
  funnel: Record<string, number>
  avg_days_per_stage: Record<string, number | null>
  period_days: number
}

export interface ForecastData {
  weighted_total: number
  by_stage: { stage: string; count: number; raw_value: number; weight_pct: number; weighted_value: number }[]
}

// ── Command-Center alerts ──────────────────────────────────────────────────────

export interface StuckDeal {
  id: number
  address: string | null
  owner_name: string | null
  contact_name: string | null
  contact_phone: string | null
  lead_score: number | null
  score_grade: string | null
  estimated_job_value: number | null
  status: string
  vertical: string | null
  zip: string | null
  stage_moved_at: string | null
  days_in_stage: number
}

export interface OverdueFollowup {
  id: number
  title: string
  due_date: string | null
  priority: TaskPriority
  property_id: number | null
  assigned_to: number | null
  address: string | null
  owner_name: string | null
  days_overdue: number
}

export interface CoolingLead {
  id: number
  address: string | null
  owner_name: string | null
  contact_name: string | null
  contact_phone: string | null
  lead_score: number | null
  score_grade: string | null
  estimated_job_value: number | null
  status: string
  vertical: string | null
  zip: string | null
  last_activity_at: string | null
}

export interface PipelineAlerts {
  stuck_deals:       { count: number; items: StuckDeal[] }
  overdue_followups: { count: number; items: OverdueFollowup[] }
  cooling_leads:     { count: number; items: CoolingLead[] }
  thresholds: {
    stuck_stage_days:   Record<string, number>
    default_stuck_days: number
    cooling_idle_days:  number
  }
}

// ── Team & performance attribution ─────────────────────────────────────────────

export interface TeamMember {
  id: number
  username: string
}

export type PerformanceDimension = 'source' | 'rep' | 'vertical'

export interface PerformanceBucket {
  bucket: string
  leads: number
  won: number
  decided: number
  win_rate: number
  revenue: number
}

export interface PerformanceBreakdown {
  dimension: PerformanceDimension
  buckets: PerformanceBucket[]
}

// ── Workflows ────────────────────────────────────────────────────────────────

export interface WorkflowTriggerConfig {
  // status_change
  from_status?: string
  to_status?: string
  // signal_event
  signal_type?: string
  // quote_event
  event?: string
  // date_offset — whitelisted source/date_field, offset relative to the anchor
  source?: string
  date_field?: string
  offset_days?: number
  // inactivity
  days?: number
  statuses?: string[]
}

export interface WorkflowActionConfig {
  // create_task
  title?: string
  due_days_offset?: number
  priority?: string
  // move_lead_status
  status?: string
  // send_notification (email-only)
  channel?: string
  subject?: string
  message?: string
  // send_template — either a single template_id, or per-channel templates with
  // a delivery mode ("sms_first" / "email_first" fall back when the preferred
  // channel has no address; "both" sends on every deliverable channel); optional
  // delay_minutes queues the send for later instead of delivering immediately
  template_id?: number
  templates?: { sms?: number; email?: number }
  delivery?: 'sms_first' | 'email_first' | 'both'
  delay_minutes?: number
}

export interface WorkflowRule {
  id: number
  name: string
  trigger_type: string
  trigger_config: WorkflowTriggerConfig
  action_type: string
  action_config: WorkflowActionConfig
  is_active: boolean
  vertical: string | null
  created_by: number | null
  created_at: string
  updated_at: string
}

export interface WorkflowRuleCreate {
  name: string
  trigger_type?: string
  trigger_config: WorkflowTriggerConfig
  action_type?: string
  action_config: WorkflowActionConfig
  is_active?: boolean
  vertical?: string
}

// ── Associated child objects (policies / orders / appointments) ──────────────

export type PolicyStatus = 'quoted' | 'active' | 'lapsed' | 'cancelled'

export interface Policy {
  id: number
  property_id: number | null
  policy_number: string | null
  carrier: string | null
  policy_type: string | null
  premium: number | null
  billing_frequency: string | null
  effective_date: string | null
  expiration_date: string | null
  status: PolicyStatus
  commission_rate: number | null
  notes: string | null
  created_by: number | null
  created_at: string
  updated_at: string
}

export interface PolicyCreate {
  property_id?: number
  policy_number?: string
  carrier?: string
  policy_type?: string
  premium?: number
  billing_frequency?: string
  effective_date?: string
  expiration_date?: string
  status?: PolicyStatus
  commission_rate?: number
  notes?: string
}

export interface PolicyPage {
  items: Policy[]
  total: number
  page: number
  page_size: number
  premium_in_force: number
  active_count: number
  next_expiration: string | null
}

export type OrderStatus = 'pending' | 'completed' | 'refunded' | 'cancelled'

export interface OrderItem {
  description?: string
  quantity?: number
  price?: number
}

export interface Order {
  id: number
  property_id: number | null
  order_number: string | null
  order_date: string | null
  total: number
  item_count: number | null
  items: OrderItem[]
  channel: string
  status: OrderStatus
  notes: string | null
  created_by: number | null
  created_at: string
  updated_at: string
}

export interface OrderCreate {
  property_id?: number
  order_number?: string
  order_date?: string
  total?: number
  item_count?: number
  items?: OrderItem[]
  channel?: string
  status?: OrderStatus
  notes?: string
}

export interface OrderPage {
  items: Order[]
  total: number
  page: number
  page_size: number
  lifetime_total: number
  completed_count: number
  last_order_date: string | null
}

export type AppointmentStatus = 'scheduled' | 'completed' | 'cancelled' | 'no_show'

export interface Appointment {
  id: number
  property_id: number | null
  assigned_to: number | null
  title: string
  location: string | null
  starts_at: string
  ends_at: string
  status: AppointmentStatus
  notes: string | null
  created_by: number | null
  created_at: string
  updated_at: string
}

export interface AppointmentCreate {
  property_id?: number
  assigned_to?: number
  title: string
  location?: string
  starts_at?: string
  ends_at?: string
  status?: AppointmentStatus
  notes?: string
}

export interface AppointmentPage {
  items: Appointment[]
  total: number
  page: number
  page_size: number
  next_at: string | null
  upcoming_count: number
}

// ── Message templates & contact-level messaging ──────────────────────────────

export type MessageChannel = 'email' | 'sms'

export interface MessageTemplate {
  id: number
  name: string
  channel: MessageChannel
  subject: string | null
  body: string
  created_by: number | null
  created_at: string
  updated_at: string
}

export interface MessageTemplateCreate {
  name: string
  channel: MessageChannel
  subject?: string
  body: string
}

// ── Saved segments ───────────────────────────────────────────────────────────

export interface Segment {
  id: number
  name: string
  filters: LeadFilters
  created_by: number | null
  created_at: string
  updated_at: string
}

export interface JobCostRow {
  property_id: number
  address: string
  estimated_value: number
  revenue: number
  amount_paid: number
  expenses: number
  profit: number
  margin_pct: number
}

// ── Non-residential audit (pipeline/residential.py) ─────────────────────────
// Reasons come in two tiers: `exclude` is structurally impossible for a home
// and is what the archive acts on; `review` is reported only, because a
// legitimate home can look like that.
export type ExclusionTier = 'exclude' | 'review'

export interface NonResidentialReason {
  count: number
  tier: ExclusionTier
  label: string
}

export interface NonResidentialSample {
  id: number
  account_number: string | null
  address: string | null
  zip: string | null
  owner_name: string | null
  property_type: string | null
  state_class: string | null
  square_footage: number | null
  year_built: number | null
  estimated_value: number | null
  lead_score: number | null
  score_grade: string | null
  status: string
  reasons: string[]
}

export interface NonResidentialAudit {
  properties: number
  flagged: number
  /** Carries at least one `exclude` reason — what the archive would act on.
   *  Smaller than the sum of by_reason counts: one bad row trips several. */
  excludable: number
  /** Excludable, but a rep has already worked it, so the archive skips it. */
  protected: number
  by_reason: Record<string, NonResidentialReason>
  samples: NonResidentialSample[]
  by_zip: { zip: string; properties: number; excludable: number }[]
  /** Flagged rows a vendor would still be billed for on the next run. */
  spend_at_risk: { billable_rows: number }
  already_archived: number
  scope: { zip: string | null }
}

export interface NonResidentialArchiveResult {
  archived_count: number
  would_archive: number
  reasons: string[]
  dry_run: boolean
  zip: string | null
  ids?: number[]
  ids_truncated?: boolean
}

// ── Platform admin (cross-tenant /api/admin surface) ─────────────────────────

export interface AdminPage<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface AdminSummary {
  accounts: number
  accounts_new_30d: number
  users_total: number
  users_active: number
  users_verified: number
  active_users_7d: number
  trials_active: number
  trials_expired: number
  paying: number
  logins_24h: number
  failed_logins_24h: number
  pipeline_runs_24h: number
  pipeline_failures_7d: number
  webhook_errors_7d: number
  prospect_signups_7d: number
}

export interface AdminAccountRow {
  id: number
  name: string
  business_type: string
  created_at: string
  plan_name: string | null
  billing_status: string | null
  trial_ends_at: string | null
  current_period_end: string | null
  users_total: number
  users_active: number
  lead_count: number
  last_activity_at: string | null
}

export interface AdminMember {
  id: number
  username: string
  email: string
  role: string
  is_active: boolean
  email_verified: boolean
  is_platform_admin: boolean
  account_id: number
  created_at: string
  last_login_at: string | null
}

export interface AdminUserRow extends AdminMember {
  account_name: string
}

export interface AdminBillingState {
  plan_name: string | null
  status: string | null
  trial_ends_at: string | null
  current_period_end: string | null
  cancel_at_period_end?: boolean | null
  has_stripe_customer?: boolean
  has_subscription?: boolean
  updated_at: string | null
}

export interface AdminAccountDetail {
  id: number
  name: string
  business_type: string
  created_at: string
  review_link: string | null
  plan: { plan_name: string; modules: Record<string, boolean>; scoring_monthly_limit: number | null; updated_at: string } | null
  modules: Record<string, boolean>
  billing: AdminBillingState | null
  members: AdminMember[]
  counts: Record<string, number>
  recent_runs: { id: number; zip: string; status: string; triggered_by: string; created_at: string; started_at: string | null; finished_at: string | null }[]
  recent_events: { id: number; event_type: string; channel: string | null; occurred_at: string; actor: string | null }[]
}

export interface AdminOrgActivityRow {
  user_id: number
  username: string
  is_active: boolean
  last_login_at: string | null
  lead_events: number
  calls: number
  logins: number
}

export interface AdminUserCreate {
  email: string
  password: string
  username?: string
  role?: string
  account_id?: number
  new_account?: { name: string; business_type?: string }
}

export interface AdminUserUpdate {
  role?: string
  is_active?: boolean
  email_verified?: boolean
  is_platform_admin?: boolean
}

export interface AdminResetLinkResult {
  reset_url: string
  emailed: boolean
  expires_in_hours: number
}

export interface AdminDeleteUserResult {
  deleted: boolean
  user_id: number
  username: string
  account_id: number
}

export interface AdminDeleteAccountResult {
  deleted: boolean
  account_id: number
  name: string
  // What the cascade destroyed, counted before the delete.
  counts: Record<string, number>
}

export interface AuthEventRow {
  id: number
  user_id: number | null
  account_id: number | null
  attempted_identifier: string | null
  method: string
  success: boolean
  failure_reason: string | null
  ip: string | null
  user_agent: string | null
  created_at: string
  username: string | null
  account_name: string | null
}

export interface AuthEventFilters {
  user_id?: number
  account_id?: number
  success?: boolean
  ip?: string
  method?: string
  page?: number
  page_size?: number
}

export interface ConfigCheck {
  key: string
  label: string
  status: 'ok' | 'warn' | 'error' | 'info'
  detail: string
}

export interface AdminSecurityReport {
  failed_by_ip: { ip: string | null; attempts: number; identifiers: number; last_at: string }[]
  failed_by_identifier: { attempted_identifier: string | null; attempts: number; ips: number; last_at: string }[]
  unverified_users: { id: number; username: string; email: string; created_at: string; account_name: string }[]
  disabled_users: { id: number; username: string; email: string; created_at: string; account_name: string }[]
  reset_tokens: { live: number; stale_unused: number }
  webhook_errors: { id: number; event_type: string; error: string | null; received_at: string }[]
  pipeline_failures: { id: number; zip: string; status: string; created_at: string; account_id: number | null; account_name: string | null; error: string | null }[]
  config_checks: ConfigCheck[]
}

export interface AdminAuditRow {
  id: number
  admin_user_id: number
  admin_username: string | null
  action: string
  target_type: string | null
  target_id: string | null
  detail: Record<string, unknown>
  created_at: string
}

export interface AdminProspectRow {
  id: number
  email: string
  name: string | null
  source: string | null
  created_at: string
  updated_at: string
}
