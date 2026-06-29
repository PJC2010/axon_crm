import type { Lead, LeadPage, LeadFilters, CustomerSearchResult, Note, HistoryEntry, LeadStatus, Task, TaskCreate, PipelineGroup, PipelineCounts, User, PipelineRun, PipelineSchedule, Expense, ExpenseCreate, ExpenseSummary, ExpenseFilters, ReceiptScanResult, Invoice, InvoiceCreate, InvoiceFilters, InvoicePayment, Quote, QuoteCreate, QuoteFilters, QuoteStatus, PublicQuote, ARSummary, AgingBucket, PnLReport, JobCostRow, TimelineEntry, PipelineStage, PipelineAnalytics, ForecastData, PipelineAlerts, PerformanceBreakdown, PerformanceDimension, TeamMember, WorkflowRule, WorkflowRuleCreate, ScoreExplanation, ImportPreview, ImportResult, Connection, SocialImportPreview, SocialImportResult, MarketingInsightsResponse } from './types'
import { getToken, clearToken } from './auth'

// Use 127.0.0.1 (not localhost): on macOS `localhost` resolves to IPv6 ::1
// first, but the dev backend binds IPv4, so localhost can fail with
// "Failed to fetch". 127.0.0.1 forces IPv4 and is unambiguous.
const BASE = (process.env.NEXT_PUBLIC_API_URL ?? 'http://127.0.0.1:8000') + '/api'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`${BASE}${path}`, { headers, ...init })

  if (res.status === 401) {
    clearToken()
    if (typeof window !== 'undefined') window.location.href = '/login'
    throw new Error('Session expired')
  }

  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText)
    throw new Error(`API ${res.status}: ${msg}`)
  }

  if (res.status === 204) return undefined as T
  return res.json()
}

// Multipart variant: do NOT set Content-Type so the browser adds the multipart
// boundary itself. Shares the 401 + error handling shape with req().
async function multipart<T>(path: string, form: FormData): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`${BASE}${path}`, { method: 'POST', headers, body: form })

  if (res.status === 401) {
    clearToken()
    if (typeof window !== 'undefined') window.location.href = '/login'
    throw new Error('Session expired')
  }
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText)
    throw new Error(`API ${res.status}: ${msg}`)
  }
  return res.json()
}

// ── Auth ──────────────────────────────────────────────────────────────────────

export function login(username: string, password: string): Promise<{ access_token: string }> {
  return req('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) })
}

// Social login: exchange a provider OIDC ID token for an Axon JWT. Same response
// shape as login(), so the caller stores access_token the same way.
export function loginWithGoogle(idToken: string): Promise<{ access_token: string }> {
  return req('/auth/oauth/google', { method: 'POST', body: JSON.stringify({ id_token: idToken }) })
}

export function loginWithApple(idToken: string): Promise<{ access_token: string }> {
  return req('/auth/oauth/apple', { method: 'POST', body: JSON.stringify({ id_token: idToken }) })
}

export function getMe(): Promise<User> {
  return req('/auth/me')
}

export function completeOnboarding(): Promise<{ ok: boolean }> {
  return req('/auth/onboarding-complete', { method: 'PATCH' })
}

export function getChecklistStatus(): Promise<import('./types').ChecklistStatus> {
  return req('/auth/checklist-status')
}

// ── Leads ─────────────────────────────────────────────────────────────────────

export function getLeads(filters: LeadFilters = {}): Promise<LeadPage> {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== '') params.set(k, String(v))
  })
  return req<LeadPage>(`/leads?${params}`)
}

export function getLead(id: number): Promise<Lead> {
  return req<Lead>(`/leads/${id}`)
}

export function getLeadByNumber(accountNumber: string): Promise<Lead> {
  return req<Lead>(`/leads/by-number/${encodeURIComponent(accountNumber)}`)
}

// Universal customer search: account number, name, address, phone, or email.
export function searchCustomers(q: string, limit = 20): Promise<CustomerSearchResult[]> {
  return req<CustomerSearchResult[]>(`/leads/search?q=${encodeURIComponent(q)}&limit=${limit}`)
}

// ── Property map ────────────────────────────────────────────────────────────────

import type { MapCell, MapPoint, MapBounds, MapFilters } from './types'

// Geohash-6 aggregates for the choropleth (zoomed-out view). Returns every cell
// with leads — no min-member threshold — so the map is complete.
export function getMapCells(filters: MapFilters = {}): Promise<MapCell[]> {
  const p = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== '') p.set(k, String(v))
  })
  return req<MapCell[]>(`/map/cells?${p}`)
}

// Property pins inside the current viewport (zoomed-in view). The bbox + hard
// server-side limit keep payloads small.
export function getMapProperties(bounds: MapBounds, filters: MapFilters = {}): Promise<MapPoint[]> {
  const p = new URLSearchParams()
  Object.entries({ ...bounds, ...filters }).forEach(([k, v]) => {
    if (v !== undefined && v !== '') p.set(k, String(v))
  })
  return req<MapPoint[]>(`/map/properties?${p}`)
}

export function updateStatus(id: number, status: LeadStatus): Promise<Lead> {
  return req<Lead>(`/leads/${id}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  })
}

export function getTimeline(leadId: number): Promise<TimelineEntry[]> {
  return req<TimelineEntry[]>(`/leads/${leadId}/timeline`)
}

export function getScoreExplanation(leadId: number): Promise<ScoreExplanation> {
  return req<ScoreExplanation>(`/leads/${leadId}/score-explanation`)
}

export interface ContactUpdate {
  contact_name?: string
  contact_phone?: string
  contact_email?: string
  contact_phone_alt?: string
  contact_email_alt?: string
  mailing_address?: string
  preferred_contact_method?: string
  best_time_to_call?: string
  assigned_to?: number | null
  lead_source?: string
}

export function updateLeadContact(id: number, body: ContactUpdate): Promise<Lead> {
  return req<Lead>(`/leads/${id}/contact`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

// On-demand skip-trace for a single lead. Throws (with the backend's message)
// when enrichment isn't configured or nothing new was found.
export function enrichLead(id: number): Promise<Lead> {
  return req<Lead>(`/leads/${id}/enrich`, { method: 'POST' })
}

export function archiveLead(id: number): Promise<Lead> {
  return req<Lead>(`/leads/${id}/archive`, { method: 'POST' })
}

export function unarchiveLead(id: number): Promise<Lead> {
  return req<Lead>(`/leads/${id}/unarchive`, { method: 'POST' })
}

export function archiveBulk(ids: number[]): Promise<{ archived_count: number; ids: number[] }> {
  return req('/leads/archive-bulk', { method: 'POST', body: JSON.stringify({ ids }) })
}

export function unarchiveBulk(ids: number[]): Promise<{ unarchived_count: number; ids: number[] }> {
  return req('/leads/unarchive-bulk', { method: 'POST', body: JSON.stringify({ ids }) })
}

export function archiveByFilter(filters: LeadFilters): Promise<{ archived_count: number; ids: number[] }> {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== '' && k !== 'page' && k !== 'page_size') params.set(k, String(v))
  })
  return req(`/leads/archive-by-filter?${params}`, { method: 'POST' })
}

export function updateJobValue(id: number, value: number): Promise<Lead> {
  return req<Lead>(`/leads/${id}/job-value`, {
    method: 'PATCH',
    body: JSON.stringify({ estimated_job_value: value }),
  })
}

// ── Notes ─────────────────────────────────────────────────────────────────────

export function getNotes(leadId: number): Promise<Note[]> {
  return req<Note[]>(`/leads/${leadId}/notes`)
}

export function addNote(leadId: number, note: string): Promise<Note> {
  return req<Note>(`/leads/${leadId}/notes`, {
    method: 'POST',
    body: JSON.stringify({ note }),
  })
}

// ── History ───────────────────────────────────────────────────────────────────

export function getHistory(leadId: number): Promise<HistoryEntry[]> {
  return req<HistoryEntry[]>(`/leads/${leadId}/history`)
}

export function addHistory(leadId: number, action: string, outcome?: string): Promise<HistoryEntry> {
  return req<HistoryEntry>(`/leads/${leadId}/history`, {
    method: 'POST',
    body: JSON.stringify({ action, outcome }),
  })
}

// ── Tasks ─────────────────────────────────────────────────────────────────────

export function getTasks(params: { due?: string; overdue?: boolean; property_id?: number; complete?: boolean } = {}): Promise<Task[]> {
  const p = new URLSearchParams()
  if (params.due) p.set('due', params.due)
  if (params.overdue) p.set('overdue', 'true')
  if (params.property_id) p.set('property_id', String(params.property_id))
  if (params.complete !== undefined) p.set('complete', String(params.complete))
  return req<Task[]>(`/tasks?${p}`)
}

export function getTaskCounts(): Promise<PipelineCounts> {
  return req<PipelineCounts>('/tasks/counts')
}

export function getLeadTasks(leadId: number): Promise<Task[]> {
  return req<Task[]>(`/leads/${leadId}/tasks`)
}

export function createTask(body: TaskCreate): Promise<Task> {
  return req<Task>('/tasks', { method: 'POST', body: JSON.stringify(body) })
}

export function completeTask(id: number): Promise<Task> {
  return req<Task>(`/tasks/${id}/complete`, { method: 'POST' })
}

export function deleteTask(id: number): Promise<void> {
  return req<void>(`/tasks/${id}`, { method: 'DELETE' })
}

// ── Pipeline / Kanban ─────────────────────────────────────────────────────────

export function getPipeline(filters: { vertical?: string; zip?: string } = {}): Promise<PipelineGroup> {
  const p = new URLSearchParams()
  if (filters.vertical) p.set('vertical', filters.vertical)
  if (filters.zip) p.set('zip', filters.zip)
  return req<PipelineGroup>(`/pipeline?${p}`)
}

export function getPipelineStages(): Promise<PipelineStage[]> {
  return req<PipelineStage[]>('/pipeline/stages')
}

export function createPipelineStage(body: { key: string; label: string; color?: string; sort_order?: number; is_terminal?: boolean }): Promise<PipelineStage> {
  return req<PipelineStage>('/pipeline/stages', { method: 'POST', body: JSON.stringify(body) })
}

export function updatePipelineStage(id: number, body: { label?: string; color?: string; sort_order?: number; is_terminal?: boolean }): Promise<PipelineStage> {
  return req<PipelineStage>(`/pipeline/stages/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
}

export function deletePipelineStage(id: number): Promise<void> {
  return req<void>(`/pipeline/stages/${id}`, { method: 'DELETE' })
}

export function getPipelineAnalytics(days = 90, vertical?: string): Promise<PipelineAnalytics> {
  const p = new URLSearchParams({ days: String(days) })
  if (vertical) p.set('vertical', vertical)
  return req<PipelineAnalytics>(`/pipeline/analytics?${p}`)
}

export function getPipelineForecast(): Promise<ForecastData> {
  return req<ForecastData>('/pipeline/forecast')
}

export function getPipelineAlerts(coolingDays?: number): Promise<PipelineAlerts> {
  const q = coolingDays ? `?cooling_days=${coolingDays}` : ''
  return req<PipelineAlerts>(`/pipeline/alerts${q}`)
}

export function getPerformance(dimension: PerformanceDimension): Promise<PerformanceBreakdown> {
  return req<PerformanceBreakdown>(`/pipeline/performance?dimension=${dimension}`)
}

// ── Team ────────────────────────────────────────────────────────────────────────

export function getTeam(): Promise<TeamMember[]> {
  return req<TeamMember[]>('/team')
}

export function getPipelineStats(): Promise<Record<string, { count: number; total_value: number }>> {
  return req('/pipeline/stats')
}

// ── Pipeline scheduling ───────────────────────────────────────────────────────

export function getSchedules(): Promise<PipelineSchedule[]> {
  return req('/pipeline-schedules')
}

export interface VolumeControls {
  top_n?: number
  center_address?: string
  radius_mi?: number
}

export function createSchedule(body: { zip: string; vertical?: string; day_of_week: string; hour: number } & VolumeControls): Promise<PipelineSchedule> {
  return req('/pipeline-schedules', { method: 'POST', body: JSON.stringify(body) })
}

export function updateSchedule(id: number, body: { is_active?: boolean; day_of_week?: string; hour?: number } & VolumeControls): Promise<PipelineSchedule> {
  return req(`/pipeline-schedules/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
}

export function deleteSchedule(id: number): Promise<void> {
  return req<void>(`/pipeline-schedules/${id}`, { method: 'DELETE' })
}

// Target exactly one of `zip` (single ZIP) or `region_id` (HCAD named
// neighborhood, seeded free from local HCAD data across its ZIPs).
export type RunTarget = { zip?: string; region_id?: string }

export function triggerRun(target: RunTarget, vertical?: string, controls: VolumeControls = {}): Promise<PipelineRun> {
  return req('/pipeline/run', { method: 'POST', body: JSON.stringify({ ...target, vertical, ...controls }) })
}

export function getPipelineRuns(limit = 20): Promise<PipelineRun[]> {
  return req(`/pipeline/runs?limit=${limit}`)
}

export function cancelRun(id: number): Promise<void> {
  return req(`/pipeline/runs/${id}`, { method: 'DELETE' })
}

export function rescoreZip(zip: string, vertical?: string): Promise<{ scored: number; zip: string; vertical: string | null }> {
  return req('/pipeline/rescore', { method: 'POST', body: JSON.stringify({ zip, vertical }) })
}

export function rescoreAll(): Promise<{ scored: number; zips: number }> {
  return req('/pipeline/rescore-all', { method: 'POST' })
}

// ── Misc ──────────────────────────────────────────────────────────────────────

export function getZips(): Promise<string[]> {
  return req<string[]>('/zips')
}

// A selectable HCAD neighborhood — a named service area spanning one or more ZIPs.
export interface Region {
  region_id: string
  name: string
  parcel_count: number
  zips: string[]
}

export function getRegions(q?: string): Promise<Region[]> {
  const qs = q ? `?q=${encodeURIComponent(q)}` : ''
  return req<Region[]>(`/regions${qs}`)
}

export function getNeighborhoods(zip?: string): Promise<import('./types').Neighborhood[]> {
  const qs = zip ? `?zip=${encodeURIComponent(zip)}` : ''
  return req<import('./types').Neighborhood[]>(`/neighborhoods${qs}`)
}

// ── Expenses ──────────────────────────────────────────────────────────────────

export function getExpenses(filters: ExpenseFilters = {}): Promise<{ items: Expense[]; total: number; page: number; page_size: number }> {
  const p = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== '') p.set(k, String(v))
  })
  return req(`/expenses?${p}`)
}

export function getExpenseSummary(year?: number, month?: number): Promise<ExpenseSummary> {
  const p = new URLSearchParams()
  if (year) p.set('year', String(year))
  if (month) p.set('month', String(month))
  return req(`/expenses/summary?${p}`)
}

export function createExpense(body: ExpenseCreate): Promise<Expense> {
  return req<Expense>('/expenses', { method: 'POST', body: JSON.stringify(body) })
}

export function updateExpense(id: number, body: Partial<ExpenseCreate>): Promise<Expense> {
  return req<Expense>(`/expenses/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
}

export function deleteExpense(id: number): Promise<void> {
  return req<void>(`/expenses/${id}`, { method: 'DELETE' })
}

// Upload a receipt photo; returns extracted fields to pre-fill the expense form.
export function scanReceipt(file: File): Promise<ReceiptScanResult> {
  const form = new FormData()
  form.append('file', file)
  return multipart<ReceiptScanResult>('/expenses/scan-receipt', form)
}

export function expenseExportUrl(filters: ExpenseFilters = {}): string {
  const p = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== '') p.set(k, String(v))
  })
  const token = getToken()
  if (token) p.set('token', token)
  return `${BASE}/expenses/export?${p}`
}

// ── Invoices ──────────────────────────────────────────────────────────────────

export function getInvoices(filters: InvoiceFilters = {}): Promise<{ items: Invoice[]; total: number; page: number; page_size: number }> {
  const p = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => { if (v !== undefined && v !== '') p.set(k, String(v)) })
  return req(`/invoices?${p}`)
}

export function getInvoice(id: number): Promise<Invoice> {
  return req<Invoice>(`/invoices/${id}`)
}

export function createInvoice(body: InvoiceCreate): Promise<Invoice> {
  return req<Invoice>('/invoices', { method: 'POST', body: JSON.stringify(body) })
}

export function updateInvoice(id: number, body: Partial<InvoiceCreate> & { status?: string }): Promise<Invoice> {
  return req<Invoice>(`/invoices/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
}

export function deleteInvoice(id: number): Promise<void> {
  return req<void>(`/invoices/${id}`, { method: 'DELETE' })
}

export function recordPayment(invoiceId: number, body: { amount: number; payment_date: string; payment_method: string; notes?: string }): Promise<InvoicePayment> {
  return req<InvoicePayment>(`/invoices/${invoiceId}/payments`, { method: 'POST', body: JSON.stringify(body) })
}

export function deletePayment(invoiceId: number, paymentId: number): Promise<void> {
  return req<void>(`/invoices/${invoiceId}/payments/${paymentId}`, { method: 'DELETE' })
}

// ── Quotes ────────────────────────────────────────────────────────────────────

export function getQuotes(filters: QuoteFilters = {}): Promise<{ items: Quote[]; total: number; page: number; page_size: number }> {
  const p = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => { if (v !== undefined && v !== '') p.set(k, String(v)) })
  return req(`/quotes?${p}`)
}

export function getQuote(id: number): Promise<Quote> {
  return req<Quote>(`/quotes/${id}`)
}

export function createQuote(body: QuoteCreate): Promise<Quote> {
  return req<Quote>('/quotes', { method: 'POST', body: JSON.stringify(body) })
}

export function updateQuote(id: number, body: Partial<QuoteCreate> & { status?: QuoteStatus }): Promise<Quote> {
  return req<Quote>(`/quotes/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
}

export function deleteQuote(id: number): Promise<void> {
  return req<void>(`/quotes/${id}`, { method: 'DELETE' })
}

export function sendQuote(id: number, channels: ('email' | 'sms')[]): Promise<Quote> {
  return req<Quote>(`/quotes/${id}/send`, { method: 'POST', body: JSON.stringify({ channels }) })
}

export function convertQuote(id: number, dueDate?: string): Promise<Invoice> {
  return req<Invoice>(`/quotes/${id}/convert`, { method: 'POST', body: JSON.stringify({ due_date: dueDate }) })
}

// Public quote endpoints — used by the customer-facing /q/[token] page, so no
// auth header and no 401-redirect handling.
async function publicReq<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail ?? `Request failed (${res.status})`)
  }
  return res.json()
}

export function getPublicQuote(token: string): Promise<PublicQuote> {
  return publicReq<PublicQuote>(`/public/quotes/${token}`)
}

export function acceptPublicQuote(token: string): Promise<PublicQuote> {
  return publicReq<PublicQuote>(`/public/quotes/${token}/accept`, { method: 'POST', body: '{}' })
}

export function declinePublicQuote(token: string, reason?: string): Promise<PublicQuote> {
  return publicReq<PublicQuote>(`/public/quotes/${token}/decline`, { method: 'POST', body: JSON.stringify({ reason }) })
}

export function getARSummary(year?: number): Promise<ARSummary> {
  const p = new URLSearchParams()
  if (year) p.set('year', String(year))
  return req(`/invoices/summary?${p}`)
}

export function getAgingReport(): Promise<AgingBucket[]> {
  return req('/invoices/aging')
}

export function invoiceExportUrl(filters: InvoiceFilters = {}): string {
  const p = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => { if (v !== undefined && v !== '') p.set(k, String(v)) })
  const token = getToken()
  if (token) p.set('token', token)
  return `${BASE}/invoices/export?${p}`
}

// Authed PDF URL (token in query string so a plain <a> link can open it).
export function invoicePdfUrl(invoiceId: number): string {
  const token = getToken()
  const q = token ? `?token=${encodeURIComponent(token)}` : ''
  return `${BASE}/invoices/${invoiceId}/pdf${q}`
}

// ── Invoice delivery ───────────────────────────────────────────────────────────

export function sendInvoice(invoiceId: number, channels: string[]): Promise<Invoice> {
  return req<Invoice>(`/invoices/${invoiceId}/send`, { method: 'POST', body: JSON.stringify({ channels }) })
}

// ── Bookkeeping reports ───────────────────────────────────────────────────────

export function getPnL(year: number): Promise<PnLReport> {
  return req(`/bookkeeping/pnl?year=${year}`)
}

export function getJobCosting(year?: number): Promise<JobCostRow[]> {
  const p = new URLSearchParams()
  if (year) p.set('year', String(year))
  return req(`/bookkeeping/job-costing?${p}`)
}

// ── Workflows ────────────────────────────────────────────────────────────────

export function getWorkflows(): Promise<WorkflowRule[]> {
  return req<WorkflowRule[]>('/workflows')
}

export function createWorkflow(body: WorkflowRuleCreate): Promise<WorkflowRule> {
  return req<WorkflowRule>('/workflows', { method: 'POST', body: JSON.stringify(body) })
}

export function updateWorkflow(id: number, body: Partial<WorkflowRuleCreate>): Promise<WorkflowRule> {
  return req<WorkflowRule>(`/workflows/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
}

export function deleteWorkflow(id: number): Promise<void> {
  return req<void>(`/workflows/${id}`, { method: 'DELETE' })
}

export function seedWorkflowDefaults(vertical: string): Promise<{ created: number; rules: WorkflowRule[] }> {
  return req(`/workflows/seed-defaults?vertical=${vertical}`, { method: 'POST' })
}

// ── Contact / lead import ───────────────────────────────────────────────────────

export function previewContactImport(file: File): Promise<ImportPreview> {
  const form = new FormData()
  form.append('file', file)
  return multipart<ImportPreview>('/imports/contacts/preview', form)
}

export function runContactImport(
  file: File,
  mapping: Record<string, string>,
  opts: { default_vertical?: string; default_status?: string } = {},
): Promise<ImportResult> {
  const form = new FormData()
  form.append('file', file)
  form.append('mapping', JSON.stringify(mapping))
  if (opts.default_vertical) form.append('default_vertical', opts.default_vertical)
  if (opts.default_status) form.append('default_status', opts.default_status)
  return multipart<ImportResult>('/imports/contacts', form)
}

// Fetch the sample CSV as a blob (auth header required) and trigger a download.
export async function downloadContactTemplate(): Promise<void> {
  const token = getToken()
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`${BASE}/imports/contacts/template`, { headers })
  if (!res.ok) throw new Error(`API ${res.status}`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'axon_import_template.csv'
  a.click()
  URL.revokeObjectURL(url)
}

// ── Connectors / connections ─────────────────────────────────────────────────

export function getConnections(): Promise<Connection[]> {
  return req<Connection[]>('/connections')
}

export function createConnection(body: { provider: string; display_name?: string }): Promise<Connection> {
  return req<Connection>('/connections', { method: 'POST', body: JSON.stringify(body) })
}

export function deleteConnection(id: number): Promise<void> {
  return req<void>(`/connections/${id}`, { method: 'DELETE' })
}

export function previewSocialImport(connId: number, file: File): Promise<SocialImportPreview> {
  const form = new FormData()
  form.append('file', file)
  return multipart<SocialImportPreview>(`/connections/${connId}/preview`, form)
}

export function runSocialImport(connId: number, file: File): Promise<SocialImportResult> {
  const form = new FormData()
  form.append('file', file)
  return multipart<SocialImportResult>(`/connections/${connId}/import`, form)
}

// ── Marketing insights ───────────────────────────────────────────────────────

export function getMarketingInsights(days = 90, provider?: string): Promise<MarketingInsightsResponse> {
  const p = new URLSearchParams({ days: String(days) })
  if (provider) p.set('provider', provider)
  return req<MarketingInsightsResponse>(`/insights/marketing?${p}`)
}

// ── Export ────────────────────────────────────────────────────────────────────

export function exportUrl(filters: LeadFilters = {}): string {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== '') params.set(k, String(v))
  })
  const token = getToken()
  if (token) params.set('token', token)
  return `${BASE}/export?${params}`
}
