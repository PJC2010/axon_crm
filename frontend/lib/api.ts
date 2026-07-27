
import type { Lead, LeadPage, LeadFilters, CustomerSearchResult, Note, HistoryEntry, LeadStatus, Task, TaskCreate, PipelineGroup, PipelineCounts, User, PipelineRun, PipelineSchedule, Expense, ExpenseCreate, ExpenseSummary, ExpenseFilters, ReceiptScanResult, Invoice, InvoiceCreate, InvoiceFilters, InvoicePayment, Quote, QuoteCreate, QuoteFilters, QuoteStatus, PublicQuote, StripeStatus, PublicPayInfo, BillingInfo, ARSummary, AgingBucket, PnLReport, JobCostRow, TimelineEntry, PipelineStage, PipelineAnalytics, ForecastData, PipelineAlerts, PerformanceBreakdown, PerformanceDimension, TeamMember, WorkflowRule, WorkflowRuleCreate, Segment, MessageTemplate, MessageTemplateCreate, Policy, PolicyCreate, PolicyPage, Order, OrderCreate, OrderPage, Appointment, AppointmentCreate, AppointmentPage, ScoreExplanation, ImportPreview, ImportResult, Connection, SocialImportPreview, SocialImportResult, MarketingInsightsResponse, AccountFeatures, BusinessTypeInfo, ObjectKpis, ModuleMap, RecordFieldDef, RecordFieldType, HeatmapMetric, HeatmapResponse, ClusterCollection, ProspectSeed, ProspectResult, BlastRadiusResult, ServiceArea, EventCollection, EventCreate, LeadEvent, LeadEventCreate, CallSettings, TrackingNumber, AvailableNumber, CallOutcome, CallLogPage } from './types'
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

// Public prospect capture (landing/preview email forms) — unauthenticated.
export function submitProspect(email: string, name?: string, source?: 'landing' | 'preview'): Promise<{ ok: boolean; detail: string }> {
  return req('/public/prospect', {
    method: 'POST',
    body: JSON.stringify({ email, name: name || null, source: source || 'landing' }),
  })
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

// Self-serve signup: creates a fresh org + owner user and returns a JWT with the
// same shape as login(), so the caller stores access_token the same way.
// smsConsent is the optional A2P opt-in from the form's checkbox — the server
// stamps it on the user row with timestamp + source 'signup' (migration 064).
export function signup(companyName: string, email: string, password: string, smsConsent = false): Promise<{ access_token: string }> {
  return req('/auth/signup', {
    method: 'POST',
    body: JSON.stringify({ company_name: companyName, email, password, sms_consent: smsConsent }),
  })
}

// Whether self-serve signup is enabled server-side (SELF_SERVE_SIGNUP).
export function getSignupStatus(): Promise<{ enabled: boolean }> {
  return req('/auth/signup-status')
}

// Always resolves with a generic ok — the server never reveals whether the
// email has an account.
export function requestPasswordReset(email: string): Promise<{ ok: boolean; detail?: string }> {
  return req('/auth/request-password-reset', { method: 'POST', body: JSON.stringify({ email }) })
}

export function resetPassword(token: string, newPassword: string): Promise<{ ok: boolean }> {
  return req('/auth/reset-password', {
    method: 'POST',
    body: JSON.stringify({ token, new_password: newPassword }),
  })
}

export function verifyEmail(token: string): Promise<{ ok: boolean }> {
  return req('/auth/verify-email', { method: 'POST', body: JSON.stringify({ token }) })
}

export function resendVerification(): Promise<{ ok: boolean; sent: boolean }> {
  return req('/auth/resend-verification', { method: 'POST' })
}

// ── Subscription billing (the account paying for Axon) ───────────────────────

export function getBilling(): Promise<BillingInfo> {
  return req('/billing')
}

// Owner-only; returns a Stripe Checkout URL to subscribe to a plan.
export function startPlanCheckout(plan: string): Promise<{ url: string }> {
  return req('/billing/checkout', { method: 'POST', body: JSON.stringify({ plan }) })
}

// Owner-only; returns a Stripe customer-portal URL (change plan, card, cancel).
export function openBillingPortal(): Promise<{ url: string }> {
  return req('/billing/portal', { method: 'POST' })
}

// ── Account profile (business name + review link) ─────────────────────────────

export function getAccountProfile(): Promise<{ name: string; review_link: string | null }> {
  return req('/account/profile')
}

export function updateAccountProfile(profile: { name?: string; review_link?: string }): Promise<{ name: string; review_link: string | null }> {
  return req('/account/profile', { method: 'PATCH', body: JSON.stringify(profile) })
}

// ── Public ZIP-sample teaser (landing page; no auth) ──────────────────────────

export interface ZipSampleLead {
  address: string          // partially masked ("18XX Westheimer Rd")
  grade: string
  score: number
  year_built: number | null
  value: string            // "~$480K" or ""
  why: string
}

export interface ZipSampleResult {
  configured: boolean
  available: boolean
  queued?: boolean
  supported?: boolean
  zip?: string
  vertical?: string | null
  total_scored?: number
  grade_a?: number
  grade_b?: number
  leads?: ZipSampleLead[]
}

export function getZipSample(zip: string, vertical?: string): Promise<ZipSampleResult> {
  const params = new URLSearchParams({ zip })
  if (vertical) params.set('vertical', vertical)
  return req(`/public/zip-sample?${params}`)
}

// Platform-wide anonymous counts for the landing page's proof chip.
// Cached server-side for a day.
export function getPublicStats(): Promise<{ properties_scored: number; zips_covered: number }> {
  return req('/public/stats')
}

// ── Per-user UI preferences (users.preferences JSONB) ─────────────────────────

export interface UserPreferences {
  checklist_hidden?: boolean
  daily_digest?: boolean
}

export function getPreferences(): Promise<UserPreferences> {
  return req('/auth/preferences')
}

export function updatePreferences(prefs: UserPreferences): Promise<UserPreferences> {
  return req('/auth/preferences', { method: 'PATCH', body: JSON.stringify(prefs) })
}

// Record or withdraw the user's consent to receive SMS from Axon (account +
// territory alerts). The server stamps consent/opt-out timestamps for the A2P
// audit trail (migration 064), so this is the Settings opt-out the privacy
// policy promises.
export function updateSmsConsent(smsConsent: boolean): Promise<{ sms_consent: boolean }> {
  return req('/auth/sms-consent', { method: 'PATCH', body: JSON.stringify({ sms_consent: smsConsent }) })
}

// Resolved plan + enabled-module map for the current account. Powers entitlement
// gating in the UI (see frontend/hooks/useEntitlements.ts).
export function getAccountFeatures(): Promise<AccountFeatures> {
  return req('/account/features')
}

export function updateAccountPlan(modules: Partial<ModuleMap>): Promise<AccountFeatures> {
  return req('/account/plan', { method: 'PATCH', body: JSON.stringify({ modules }) })
}

// Switch the account's business type (terminology/categories preset). Returns the
// new business-type profile. Callers should clearEntitlementsCache() afterward.
// With applyDefaults, the preset's provisioning pack (missing stages, custom
// fields, default workflows, plan-bounded modules) is also seeded.
export function updateBusinessType(business_type: string, applyDefaults = false): Promise<{
  business_type: string; property_based: boolean
  terminology: Record<string, string>; categories: { value: string; label: string }[]
  kpis?: string[]; objects?: string[]
  provisioned?: { stages: number; fields: number; workflows: number; modules_enabled: number }
}> {
  return req('/account/business-type', {
    method: 'PATCH',
    body: JSON.stringify({ business_type, apply_defaults: applyDefaults }),
  })
}

// Business-type catalog for the onboarding picker.
export function getBusinessTypes(): Promise<BusinessTypeInfo[]> {
  return req('/account/business-types')
}

// Child-object dashboard aggregates (premium in force, revenue MTD, …). Keys
// are present only for modules the account has enabled.
export function getObjectKpis(): Promise<ObjectKpis> {
  return req('/objects/kpis')
}

// Recompute lead scores from child-object roll-ups (insurance renewal / retail
// RFM). Owner-only; 400 for business types that aren't scored this way.
export function rescoreObjects(): Promise<{ updated: number }> {
  return req('/objects/rescore', { method: 'POST' })
}

// ── Custom record fields ────────────────────────────────────────────────────────

export function getRecordFields(): Promise<RecordFieldDef[]> {
  return req('/record-fields')
}

export function createRecordField(body: {
  label: string; field_type: RecordFieldType; options?: string[]; sort_order?: number
}): Promise<RecordFieldDef> {
  return req('/record-fields', { method: 'POST', body: JSON.stringify(body) })
}

export function updateRecordField(id: number, body: Partial<{
  label: string; field_type: RecordFieldType; options: string[]; sort_order: number
}>): Promise<RecordFieldDef> {
  return req(`/record-fields/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
}

export function deleteRecordField(id: number): Promise<void> {
  return req(`/record-fields/${id}`, { method: 'DELETE' })
}

// Merge custom field values into a record; a value of null clears that key.
export function updateLeadCustomFields(
  leadId: number, values: Record<string, unknown>,
): Promise<{ custom_fields: Record<string, unknown> }> {
  return req(`/leads/${leadId}/custom-fields`, { method: 'PATCH', body: JSON.stringify({ values }) })
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

// ── Geo layer (Phase 2–3): clusters, heatmap, prospecting, neighbors ────────────

// H3-hex aggregates for the heatmap overlay (customer density or average score).
export function getGeoHeatmap(metric: HeatmapMetric = 'density'): Promise<HeatmapResponse> {
  return req<HeatmapResponse>(`/geo/heatmap?metric=${metric}`)
}

// Customer clusters (DBSCAN hulls) as a GeoJSON FeatureCollection.
export function getGeoClusters(): Promise<ClusterCollection> {
  return req<ClusterCollection>('/geo/clusters')
}

// Cluster-seeded prospecting: pull → dedupe → ingest → score around a seed.
export function prospectArea(body: {
  seed: ProspectSeed; radius_m?: number; vertical?: string; preset?: Record<string, unknown>
}): Promise<ProspectResult> {
  return req<ProspectResult>('/geo/prospect', { method: 'POST', body: JSON.stringify(body) })
}

// Blast radius around a completed job — ranked door-knock/mail targets.
export function getBlastRadius(job_id: number, radius_m = 150, limit = 25): Promise<BlastRadiusResult> {
  return req<BlastRadiusResult>('/geo/neighbors', {
    method: 'POST', body: JSON.stringify({ job_id, radius_m, limit }),
  })
}

// The account's service-area polygon (derived hull or user-drawn), as GeoJSON.
export function getServiceArea(): Promise<ServiceArea> {
  return req<ServiceArea>('/geo/service-area')
}

export function putServiceArea(polygon: object): Promise<{ id: number; source: string }> {
  return req('/geo/service-area', { method: 'PUT', body: JSON.stringify({ polygon }) })
}

// Event layer (Phase 4): polygons whose leads get a scoring bonus.
export function getGeoEvents(): Promise<EventCollection> {
  return req<EventCollection>('/geo/events')
}
export function createGeoEvent(body: EventCreate): Promise<{ id: number }> {
  return req('/geo/events', { method: 'POST', body: JSON.stringify(body) })
}
export function deleteGeoEvent(id: number): Promise<{ deleted: number }> {
  return req(`/geo/events/${id}`, { method: 'DELETE' })
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

// Scoring feedback loop: append a lead outcome event. Routine events fire
// automatically server-side; this is the explicit path (the "Bad lead" action
// emits a 'disqualified' event with a reason in metadata).
export function createLeadEvent(leadId: number, body: LeadEventCreate): Promise<LeadEvent> {
  return req<LeadEvent>(`/leads/${leadId}/events`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function getLeadEvents(leadId: number): Promise<LeadEvent[]> {
  return req<LeadEvent[]>(`/leads/${leadId}/events`)
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

// Where step 1 gets addresses. 'hcad' seeds free from local Harris County data
// (RentCast then only gap-fills NULLs); 'rentcast' pays for the address scan.
// Omit to use the server's SEED_SOURCE default. Region runs always use HCAD.
export type SeedSource = 'rentcast' | 'hcad'

export function triggerRun(target: RunTarget, vertical?: string, controls: VolumeControls = {}, seedSource?: SeedSource): Promise<PipelineRun> {
  return req('/pipeline/run', { method: 'POST', body: JSON.stringify({ ...target, vertical, ...controls, seed_source: seedSource }) })
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
  Object.entries(filters).forEach(([k, v]) => { if (v !== undefined && v !== '') p.set(k, String(v)) })
  return req(`/expenses?${p}`)
}

export function getExpenseSummary(year?: number, month?: number): Promise<ExpenseSummary> {
  const p = new URLSearchParams()
  if (year) p.set('year', String(year))
  if (month) p.set('month', String(month))
  return req<ExpenseSummary>(`/expenses/summary?${p}`)
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
  Object.entries(filters).forEach(([k, v]) => { if (v !== undefined && v !== '') p.set(k, String(v)) })
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
  return req<ARSummary>(`/invoices/summary?${p}`)
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

// ── Online payments (Stripe Connect) ──────────────────────────────────────────

export function getStripeStatus(): Promise<StripeStatus> {
  return req('/stripe/status')
}

// Returns the hosted Stripe onboarding URL; navigate the browser to it.
export function connectStripe(): Promise<{ url: string }> {
  return req('/stripe/connect', { method: 'POST', body: '{}' })
}

export function createInvoiceCheckout(invoiceId: number): Promise<{ url: string }> {
  return req(`/invoices/${invoiceId}/checkout`, { method: 'POST', body: '{}' })
}

export function getPublicPayInfo(token: string): Promise<PublicPayInfo> {
  return publicReq<PublicPayInfo>(`/public/pay/${token}`)
}

export function createPublicCheckout(token: string): Promise<{ url: string }> {
  return publicReq<{ url: string }>(`/public/pay/${token}/checkout`, { method: 'POST', body: '{}' })
}

// ── Bookkeeping reports ───────────────────────────────────────────────────────

export function getPnL(year: number): Promise<PnLReport> {
  return req(`/bookkeeping/pnl?year=${year}`)
}

export function getJobCosting(year?: number): Promise<JobCostRow[]> {
  const p = new URLSearchParams()
  if (year) p.set('year', String(year))
  return req<JobCostRow[]>(`/bookkeeping/job-costing?${p}`)
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

// ── Associated child objects (policies / orders / appointments) ──────────────

export function getPolicies(params: { property_id?: number; status?: string; page?: number; page_size?: number } = {}): Promise<PolicyPage> {
  const p = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== '') p.set(k, String(v)) })
  return req<PolicyPage>(`/policies?${p}`)
}

export function createPolicy(body: PolicyCreate): Promise<Policy> {
  return req<Policy>('/policies', { method: 'POST', body: JSON.stringify(body) })
}

export function updatePolicy(id: number, body: Partial<PolicyCreate>): Promise<Policy> {
  return req<Policy>(`/policies/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
}

export function deletePolicy(id: number): Promise<void> {
  return req<void>(`/policies/${id}`, { method: 'DELETE' })
}

export function getOrders(params: { property_id?: number; status?: string; channel?: string; page?: number; page_size?: number } = {}): Promise<OrderPage> {
  const p = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== '') p.set(k, String(v)) })
  return req<OrderPage>(`/orders?${p}`)
}

export function createOrder(body: OrderCreate): Promise<Order> {
  return req<Order>('/orders', { method: 'POST', body: JSON.stringify(body) })
}

export function updateOrder(id: number, body: Partial<OrderCreate>): Promise<Order> {
  return req<Order>(`/orders/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
}

export function deleteOrder(id: number): Promise<void> {
  return req<void>(`/orders/${id}`, { method: 'DELETE' })
}

export function getAppointments(params: { property_id?: number; status?: string; from?: string; to?: string; page?: number; page_size?: number } = {}): Promise<AppointmentPage> {
  const p = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== '') p.set(k, String(v)) })
  return req<AppointmentPage>(`/appointments?${p}`)
}

export function createAppointment(body: AppointmentCreate): Promise<Appointment> {
  return req<Appointment>('/appointments', { method: 'POST', body: JSON.stringify(body) })
}

export function updateAppointment(id: number, body: Partial<AppointmentCreate>): Promise<Appointment> {
  return req<Appointment>(`/appointments/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
}

export function deleteAppointment(id: number): Promise<void> {
  return req<void>(`/appointments/${id}`, { method: 'DELETE' })
}

// ── Message templates & contact-level messaging ──────────────────────────────

export function getMessageTemplates(): Promise<MessageTemplate[]> {
  return req<MessageTemplate[]>('/message-templates')
}

export function createMessageTemplate(body: MessageTemplateCreate): Promise<MessageTemplate> {
  return req<MessageTemplate>('/message-templates', { method: 'POST', body: JSON.stringify(body) })
}

export function updateMessageTemplate(id: number, body: Partial<MessageTemplateCreate>): Promise<MessageTemplate> {
  return req<MessageTemplate>(`/message-templates/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
}

export function deleteMessageTemplate(id: number): Promise<void> {
  return req<void>(`/message-templates/${id}`, { method: 'DELETE' })
}

export function sendLeadMessage(leadId: number, body: {
  template_id?: number; channel?: string; subject?: string; body?: string; policy_id?: number
}): Promise<{ sent: boolean; channel: string; to: string }> {
  return req(`/leads/${leadId}/message`, { method: 'POST', body: JSON.stringify(body) })
}

// ── Saved segments ───────────────────────────────────────────────────────────

export function getSegments(): Promise<Segment[]> {
  return req<Segment[]>('/segments')
}

export function createSegment(name: string, filters: LeadFilters): Promise<Segment> {
  return req<Segment>('/segments', { method: 'POST', body: JSON.stringify({ name, filters }) })
}

export function updateSegment(id: number, body: { name?: string; filters?: LeadFilters }): Promise<Segment> {
  return req<Segment>(`/segments/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
}

export function deleteSegment(id: number): Promise<void> {
  return req<void>(`/segments/${id}`, { method: 'DELETE' })
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
  return _downloadCsv('/imports/contacts/template', 'axon_import_template.csv')
}

// ── Retail orders import (Square / Shopify) ──────────────────────────────────

export function previewOrderImport(file: File): Promise<ImportPreview> {
  const form = new FormData()
  form.append('file', file)
  return multipart<ImportPreview>('/imports/orders/preview', form)
}

export function runOrderImport(
  file: File,
  mapping: Record<string, string>,
  opts: { default_channel?: string } = {},
): Promise<ImportResult> {
  const form = new FormData()
  form.append('file', file)
  form.append('mapping', JSON.stringify(mapping))
  if (opts.default_channel) form.append('default_channel', opts.default_channel)
  return multipart<ImportResult>('/imports/orders', form)
}

export async function downloadOrderTemplate(): Promise<void> {
  return _downloadCsv('/imports/orders/template', 'axon_orders_template.csv')
}

async function _downloadCsv(path: string, filename: string): Promise<void> {
  const token = getToken()
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`${BASE}${path}`, { headers })
  if (!res.ok) throw new Error(`API ${res.status}`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
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

// ── Call tracking ────────────────────────────────────────────────────────────

export function getCallSettings(): Promise<CallSettings> {
  return req<CallSettings>('/calls/settings')
}

export function updateCallSettings(forwardTo: string): Promise<{ ok: boolean; number: TrackingNumber | null }> {
  return req('/calls/settings', { method: 'PATCH', body: JSON.stringify({ forward_to: forwardTo }) })
}

export function searchCallNumbers(params: { area_code?: string; contains?: string } = {}): Promise<{ numbers: AvailableNumber[] }> {
  const p = new URLSearchParams()
  if (params.area_code) p.set('area_code', params.area_code)
  if (params.contains) p.set('contains', params.contains)
  return req(`/calls/numbers/available?${p}`)
}

export function purchaseCallNumber(phoneNumber: string, forwardTo?: string): Promise<{ ok: boolean; number: TrackingNumber | null }> {
  return req('/calls/numbers', {
    method: 'POST',
    body: JSON.stringify({ phone_number: phoneNumber, forward_to: forwardTo || null }),
  })
}

export function releaseCallNumber(numberId: number): Promise<{ ok: boolean }> {
  return req(`/calls/numbers/${numberId}`, { method: 'DELETE' })
}

export function getCalls(params: { limit?: number; offset?: number; outcome?: CallOutcome } = {}): Promise<CallLogPage> {
  const p = new URLSearchParams()
  if (params.limit) p.set('limit', String(params.limit))
  if (params.offset) p.set('offset', String(params.offset))
  if (params.outcome) p.set('outcome', params.outcome)
  return req<CallLogPage>(`/calls?${p}`)
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

// QuickBooks Online import-format downloads (invoices/expenses). Same
// token-in-query pattern as exportUrl so <a download> links work.
export function qboExportUrl(kind: 'invoices' | 'expenses', start?: string, end?: string): string {
  const params = new URLSearchParams()
  if (start) params.set('start', start)
  if (end) params.set('end', end)
  const token = getToken()
  if (token) params.set('token', token)
  return `${BASE}/export/qbo/${kind}?${params}`
}
