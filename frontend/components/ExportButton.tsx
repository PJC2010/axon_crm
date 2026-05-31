'use client'
import { Download } from 'lucide-react'
import { exportUrl } from '@/lib/api'
import type { LeadFilters } from '@/lib/types'

interface Props { filters: LeadFilters }

export function ExportButton({ filters }: Props) {
  function handleClick() {
    const a = document.createElement('a')
    a.href = exportUrl(filters)
    a.download = `leads_${filters.zip ?? 'all'}.csv`
    a.click()
  }

  return (
    <button onClick={handleClick} className="btn-secondary" style={{ fontSize: 13, padding: '5px 12px' }}>
      <Download size={13} strokeWidth={1.5} />
      Export CSV
    </button>
  )
}
