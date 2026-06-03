export type LeadStatus = 'new' | 'contacted' | 'qualified' | 'not_interested' | 'converted' | 'quote_sent' | 'won' | 'lost'
export type ScoreGrade = 'A' | 'B' | 'C' | 'D'
export type TaskPriority = 'low' | 'normal' | 'high' | 'urgent'

export interface Lead {
  id: number
  address: string
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
  zip_median_income: number | null
  permit_count_24mo: number | null
  lead_score: number | null
  score_grade: ScoreGrade | null
  vertical: string | null
  status: LeadStatus
  estimated_job_value: number | null
  stage_moved_at: string | null
  score_updated_at: string | null
  created_at: string | null
  updated_at: string | null
  archived_at: string | null
}

export interface LeadPage {
  total: number
  page: number
  page_size: number
  results: Lead[]
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
  type: 'history' | 'note' | 'task'
  title: string
  detail: string | null
  created_at: string
}

export interface LeadFilters {
  zip?: string
  grade?: string
  vertical?: string
  status?: string
  sort?: string
  page?: number
  page_size?: number
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

export interface PipelineCardLead {
  id: number
  address: string
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

export interface User {
  id: number
  username: string
  email: string
  role: string
  is_active: boolean
  onboarding_complete: boolean
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
  created_at: string
}

export interface PipelineRun {
  id: number
  schedule_id: number | null
  zip: string
  vertical: string | null
  status: 'queued' | 'running' | 'done' | 'failed'
  triggered_by: string
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

// ── Workflows ────────────────────────────────────────────────────────────────

export interface WorkflowRule {
  id: number
  name: string
  trigger_type: string
  trigger_config: { from_status?: string; to_status?: string }
  action_type: string
  action_config: { title?: string; due_days_offset?: number; priority?: string }
  is_active: boolean
  vertical: string | null
  created_by: number | null
  created_at: string
  updated_at: string
}

export interface WorkflowRuleCreate {
  name: string
  trigger_type?: string
  trigger_config: { from_status?: string; to_status?: string }
  action_type?: string
  action_config: { title?: string; due_days_offset?: number; priority?: string }
  is_active?: boolean
  vertical?: string
}

export interface JobCostRow {
  property_id: number
  address: string
  revenue: number
  amount_paid: number
  expenses: number
  profit: number
  margin_pct: number
}
