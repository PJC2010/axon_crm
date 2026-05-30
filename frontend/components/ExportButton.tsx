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
    <button
      onClick={handleClick}
      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-[6px] border border-[#E2DDD5] bg-white text-[#16181D]/70 text-xs font-medium hover:border-[#1A5A75]/40 hover:text-[#1A5A75] transition-colors cursor-pointer"
    >
      <Download size={13} strokeWidth={1.5} />
      Export CSV
    </button>
  )
}
