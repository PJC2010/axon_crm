import type { Lead, LeadPage, LeadFilters, Note, HistoryEntry, LeadStatus, Task, TaskCreate, PipelineGroup, PipelineCounts, User, PipelineRun, PipelineSchedule, Expense, ExpenseCreate, ExpenseSummary, ExpenseFilters, Invoice, InvoiceCreate, InvoiceFilters, InvoicePayment, ARSummary, AgingBucket, PnLReport, JobCostRow, TimelineEntry, PipelineStage, PipelineAnalytics, ForecastData, WorkflowRule, WorkflowRuleCreate, ConnectStatus, PublicInvoiceView } from './types'
import { getToken, clearToken } from './auth'

const BASE = (process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000') + '/api'

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

// ── Auth ──────────────────────────────────────────────────────────────────────

export function login(username: string, password: string): Promise<{ access_token: string }> {
  return req('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) })
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

export function updateStatus(id: number, status: LeadStatus): Promise<Lead> {
  return req<Lead>(`/leads/${id}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  })
}

export function getTimeline(leadId: number): Promise<TimelineEntry[]> {
  return req<TimelineEntry[]>(`/leads/${leadId}/timeline`)
}

export function updateLeadContact(id: number, body: { contact_phone?: string; contact_email?: string; contact_name?: string }): Promise<Lead> {
  return req<Lead>(`/leads/${id}/contact`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
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

export function getPipelineStats(): Promise<Record<string, { count: number; total_value: number }>> {
  return req('/pipeline/stats')
}

// ── Pipeline scheduling ───────────────────────────────────────────────────────

export function getSchedules(): Promise<PipelineSchedule[]> {
  return req('/pipeline-schedules')
}

export function createSchedule(body: { zip: string; vertical?: string; day_of_week: string; hour: number }): Promise<PipelineSchedule> {
  return req('/pipeline-schedules', { method: 'POST', body: JSON.stringify(body) })
}

export function updateSchedule(id: number, body: { is_active?: boolean; day_of_week?: string; hour?: number }): Promise<PipelineSchedule> {
  return req(`/pipeline-schedules/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
}

export function deleteSchedule(id: number): Promise<void> {
  return req<void>(`/pipeline-schedules/${id}`, { method: 'DELETE' })
}

export function triggerRun(zip: string, vertical?: string): Promise<PipelineRun> {
  return req('/pipeline/run', { method: 'POST', body: JSON.stringify({ zip, vertical }) })
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

// ── Payments / Stripe Connect ──────────────────────────────────────────────────

export function startStripeOnboarding(): Promise<{ url: string }> {
  return req('/stripe/connect/onboard', { method: 'POST' })
}

export function getStripeStatus(): Promise<ConnectStatus> {
  return req<ConnectStatus>('/stripe/connect/status')
}

export function createCheckoutSession(invoiceId: number): Promise<{ url: string }> {
  return req(`/invoices/${invoiceId}/checkout-session`, { method: 'POST' })
}

export function sendInvoice(invoiceId: number, channels: string[]): Promise<Invoice> {
  return req<Invoice>(`/invoices/${invoiceId}/send`, { method: 'POST', body: JSON.stringify({ channels }) })
}

// Public (unauthenticated) — must NOT use req(): no bearer token, no /login redirect.
async function publicReq<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' }, ...init,
  })
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText)
    throw new Error(`API ${res.status}: ${msg}`)
  }
  return res.json()
}

export function getPublicInvoice(token: string): Promise<PublicInvoiceView> {
  return publicReq<PublicInvoiceView>(`/public/invoices/${token}`)
}

export function startPublicCheckout(token: string): Promise<{ url: string }> {
  return publicReq(`/public/invoices/${token}/checkout`, { method: 'POST' })
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
