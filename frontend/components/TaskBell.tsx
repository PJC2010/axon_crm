'use client'
import { useEffect, useState } from 'react'
import { Bell } from 'lucide-react'
import Link from 'next/link'
import { getTaskCounts } from '@/lib/api'

export function TaskBell() {
  const [counts, setCounts] = useState({ today: 0, overdue: 0 })

  useEffect(() => {
    let mounted = true
    const fetch = async () => {
      try {
        const c = await getTaskCounts()
        if (mounted) setCounts(c)
      } catch { /* not authenticated yet */ }
    }
    fetch()
    const id = setInterval(fetch, 60_000)
    return () => { mounted = false; clearInterval(id) }
  }, [])

  const total = counts.today + counts.overdue

  return (
    <Link href="/tasks" className="dash-icon-btn" style={{ position: 'relative', textDecoration: 'none', color: 'inherit' }} title={`${counts.overdue} overdue, ${counts.today} due today`}>
      <Bell size={13} strokeWidth={1.5} />
      {total > 0 && (
        <span style={{
          position: 'absolute',
          top: 2,
          right: 2,
          minWidth: 14,
          height: 14,
          borderRadius: 7,
          background: counts.overdue > 0 ? 'var(--color-danger)' : 'var(--color-accent)',
          color: '#fff',
          fontSize: 9,
          fontWeight: 700,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          lineHeight: 1,
          padding: '0 3px',
        }}>
          {total > 99 ? '99+' : total}
        </span>
      )}
    </Link>
  )
}
