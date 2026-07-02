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
  // Account-defined custom field values, keyed by RecordFieldDef.key.
  custom_fields?: Record<string, unknown>
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

export interface LeadPage {
  total: number
  page: number
  page_size: number
  results: Lead[]
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
}

export interface TimelineEntry {
  id: number
  property_id: number
  type: 'history' | 'note' | 'task' | 'signal'
  title: string
  detail: string | null
  created_at: string
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
  errors: string[]
}

// ── Connectors / connections ────────────────────────────────────────────────────

export interface Connection {
  id: number
  provider: string                 // 'meta_facebook' | 'meta_instagram'
  display_name: string | null
  status: string                   // connected | disconnected | error
  auth_type: string                // file | oauth
  last_synced_at: string | null
  created_at: string
}

export interface SocialImportPreview {
  export_kind: string | null
  metric_rows: number
  post_rows: number
  period_start: string | null
  period_end: string | null
  sample_metrics: Record<string, unknown>[]
  sample_posts: Record<string, unknown>[]
  errors: string[]
}

export interface SocialImportResult {
  import_id: number
  metrics_imported: number
  posts_imported: number
  skipped: number
  errors: string[]
}

// ── Marketing insights ──────────────────────────────────────────────────────────

export interface MarketingInsight {
  id: string
  severity: 'positive' | 'warning' | 'action'
  category: 'content' | 'audience' | 'paid' | 'cadence' | 'conversion'
  title: string
  message: string
  recommended_action: string
  supporting_metric: { label?: string; value?: string | number; comparison?: string }
}

export interface MarketingInsightsResponse {
  insights: MarketingInsight[]
  period_days: number
  has_data: boolean
  last_synced_at: string | null
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
  | 'marketing'
  | 'automation'
  | 'policies'
  | 'orders'
  | 'appointments'

export type ModuleMap = Record<ModuleKey, boolean>

// A category option ("vertical" in home-services terms). Driven by business type.
export interface Category {
  value: string
  label: string
}

export interface AccountFeatures {
  plan_name: string
  modules: ModuleMap
  // Business-type profile (see api/business_types.py). Optional so older payloads
  // / pre-load states degrade gracefully to home-services defaults.
  business_type?: string
  property_based?: boolean
  terminology?: Record<string, string>
  categories?: Category[]
  // Dashboard KPI tile ids + child objects for this business type (Phase 6).
  kpis?: string[]
  objects?: string[]
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
  onboarding_complete: boolean
  // Populated by GET /auth/me; enabled feature modules for this user's account.
  modules?: Partial<ModuleMap>
  business_type?: string
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
}

export interface InvoiceFilters {
  status?: InvoiceStatus
  year?: number
  month?: number
  property_id?: number
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
  property_id?: number
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
  priority: string
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
  // send_template
  template_id?: number
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
  channel: string | null
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
  starts_at: string
  ends_at: string
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
