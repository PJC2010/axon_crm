import type { Lead, LeadPage, LeadFilters, Note, HistoryEntry, LeadStatus } from './types'

const BASE = (process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000') + '/api'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText)
    throw new Error(`API ${res.status}: ${msg}`)
  }
  return res.json()
}

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

export function getNotes(leadId: number): Promise<Note[]> {
  return req<Note[]>(`/leads/${leadId}/notes`)
}

export function addNote(leadId: number, note: string): Promise<Note> {
  return req<Note>(`/leads/${leadId}/notes`, {
    method: 'POST',
    body: JSON.stringify({ note }),
  })
}

export function getHistory(leadId: number): Promise<HistoryEntry[]> {
  return req<HistoryEntry[]>(`/leads/${leadId}/history`)
}

export function addHistory(leadId: number, action: string, outcome?: string): Promise<HistoryEntry> {
  return req<HistoryEntry>(`/leads/${leadId}/history`, {
    method: 'POST',
    body: JSON.stringify({ action, outcome }),
  })
}

export function getZips(): Promise<string[]> {
  return req<string[]>('/zips')
}

export function exportUrl(filters: LeadFilters = {}): string {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== '') params.set(k, String(v))
  })
  return `${BASE}/export?${params}`
}
