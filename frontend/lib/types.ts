export type LeadStatus = 'new' | 'contacted' | 'qualified' | 'not_interested' | 'converted'
export type ScoreGrade = 'A' | 'B' | 'C' | 'D'

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
  zip_median_income: number | null
  permit_count_24mo: number | null
  lead_score: number | null
  score_grade: ScoreGrade | null
  vertical: string | null
  status: LeadStatus
  score_updated_at: string | null
  created_at: string | null
  updated_at: string | null
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

export interface LeadFilters {
  zip?: string
  grade?: string
  vertical?: string
  status?: string
  sort?: string
  page?: number
  page_size?: number
}
