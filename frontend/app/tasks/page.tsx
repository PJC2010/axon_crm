'use client'
import { SkeletonCards } from '@/components/ds'
import { useEffect, useState, useCallback } from 'react'
import Link from 'next/link'
import { ArrowLeft, Home } from 'lucide-react'
import { getTasks } from '@/lib/api'
import { AuthGuard } from '@/components/AuthGuard'
import type { Task } from '@/lib/types'
import { TaskList } from '@/components/TaskList'
import { TaskForm } from '@/components/TaskForm'

function TasksPage() {
  const [overdue, setOverdue] = useState<Task[]>([])
  const [today, setToday] = useState<Task[]>([])
  const [upcoming, setUpcoming] = useState<Task[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [od, td, up] = await Promise.all([
        getTasks({ overdue: true }),
        getTasks({ due: 'today' }),
        getTasks({}),
      ])
      setOverdue(od)
      setToday(td)
      // upcoming = not overdue, not today, not complete
      const todayStr = new Date().toISOString().slice(0, 10)
      setUpcoming(up.filter(t => t.due_date && t.due_date > todayStr))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  return (
    <div style={{ minHeight: '100dvh', background: 'transparent' }}>
      <header style={{
        height: 64, padding: '0 28px', display: 'flex', alignItems: 'center', gap: 16,
        borderBottom: '1px solid var(--color-ink-200)', background: 'var(--color-paper)',
      }}>
        <Link href="/dashboard" className="dash-icon-btn" style={{ textDecoration: 'none', color: 'inherit' }}>
          <ArrowLeft size={15} strokeWidth={1.5} />
        </Link>
        <Link href="/home" title="Home" className="dash-icon-btn" style={{ textDecoration: 'none', color: 'inherit' }}>
          <Home size={15} strokeWidth={1.5} />
        </Link>
        <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 600, color: 'var(--color-ink-900)', margin: 0 }}>
          Tasks
        </h1>
      </header>

      <main id="main" style={{ maxWidth: 680, margin: '0 auto', padding: '28px 20px' }}>
        <div style={{ marginBottom: 28 }}>
          <h2 className="t-eyebrow" style={{ marginBottom: 10 }}>New task</h2>
          <TaskForm onCreated={load} />
        </div>

        {loading ? (
          <SkeletonCards count={4} h={58} gap={8} />
        ) : (
          <>
            {overdue.length > 0 && (
              <section style={{ marginBottom: 24 }}>
                <h2 className="t-eyebrow" style={{ color: 'var(--color-danger)', marginBottom: 10 }}>
                  Overdue ({overdue.length})
                </h2>
                <TaskList tasks={overdue} onUpdate={load} />
              </section>
            )}

            <section style={{ marginBottom: 24 }}>
              <h2 className="t-eyebrow" style={{ marginBottom: 10 }}>
                Due today ({today.length})
              </h2>
              <TaskList tasks={today} onUpdate={load} />
            </section>

            {upcoming.length > 0 && (
              <section>
                <h2 className="t-eyebrow" style={{ marginBottom: 10 }}>
                  Upcoming ({upcoming.length})
                </h2>
                <TaskList tasks={upcoming} onUpdate={load} />
              </section>
            )}
          </>
        )}
      </main>
    </div>
  )
}

export default function TasksPageGuarded() {
  return <AuthGuard><TasksPage /></AuthGuard>
}
