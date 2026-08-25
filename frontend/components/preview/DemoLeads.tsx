'use client'
import { useMemo, useState } from 'react'
import { Plus, Search } from 'lucide-react'
import type { Lead, LeadStatus, ScoreGrade } from '@/lib/types'
import { LeadCard } from '@/components/lead/LeadCard'
import { DEMO_CATEGORIES } from '@/lib/demoData'

interface Props {
  leads: Lead[]
  onOpen: (id: number) => void
  onStatusChange: (id: number, s: LeadStatus) => void
  onNewLead: () => void
  /** Bulk-bar buttons are simulated in the demo — surface what they'd do. */
  onFakeAction: (msg: string) => void
}

const GRADES: ScoreGrade[] = ['A', 'B', 'C', 'D']

/**
 * The lead list, demo-fed: the product's own mobile-first LeadCard rows with
 * working status changes, selection, search, and grade filtering — no login.
 */
export function DemoLeads({ leads, onOpen, onStatusChange, onNewLead, onFakeAction }: Props) {
  const [query, setQuery] = useState('')
  const [grade, setGrade] = useState<ScoreGrade | null>(null)
  const [selected, setSelected] = useState<Set<number>>(new Set())

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return [...leads]
      .sort((a, b) => (b.lead_score ?? 0) - (a.lead_score ?? 0))
      .filter(l => (grade ? l.score_grade === grade : true))
      .filter(l => {
        if (!q) return true
        return [l.address, l.owner_name, l.contact_name, l.zip]
          .some(v => v?.toLowerCase().includes(q))
      })
  }, [leads, query, grade])

  const toggleSelect = (id: number) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div>
      {/* Toolbar: search + grade filter + new lead */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8, flex: '1 1 200px', minWidth: 0,
          background: 'var(--color-surface)', border: '1px solid var(--color-ink-200)',
          borderRadius: 'var(--radius-pill)', padding: '0 14px', minHeight: 40,
        }}>
          <Search size={14} strokeWidth={1.5} color="var(--color-ink-400)" style={{ flexShrink: 0 }} />
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search address, owner, ZIP…"
            aria-label="Search leads"
            style={{
              flex: 1, minWidth: 0, border: 'none', outline: 'none', background: 'transparent',
              fontSize: 13, color: 'var(--color-ink-900)', fontFamily: 'var(--font-sans)',
            }}
          />
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {GRADES.map(g => {
            const active = grade === g
            return (
              <button
                key={g}
                onClick={() => setGrade(active ? null : g)}
                aria-pressed={active}
                title={`Show only grade ${g}`}
                style={{
                  minWidth: 36, minHeight: 36, borderRadius: 'var(--radius-pill)',
                  border: `1px solid ${active ? 'var(--color-accent)' : 'var(--color-ink-200)'}`,
                  background: active ? 'var(--color-accent)' : 'var(--color-surface)',
                  color: active ? 'white' : 'var(--color-ink-600)',
                  fontSize: 13, fontWeight: 700, cursor: 'pointer',
                }}
              >
                {g}
              </button>
            )
          })}
        </div>
        <button
          onClick={onNewLead}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '0 16px', minHeight: 40, borderRadius: 'var(--radius-pill)',
            background: 'var(--color-accent)', color: 'white', border: 'none',
            fontSize: 13, fontWeight: 600, cursor: 'pointer', whiteSpace: 'nowrap',
          }}
        >
          <Plus size={14} strokeWidth={2} /> New Lead
        </button>
      </div>

      {/* Bulk bar */}
      {selected.size > 0 && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
          padding: '10px 14px', marginBottom: 12,
          background: 'var(--color-accent-50, var(--color-surface))',
          border: '1px solid var(--color-accent-300)', borderRadius: 'var(--radius-card)',
        }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-ink-900)' }}>
            {selected.size} selected
          </span>
          {['Export CSV', 'Assign to rep', 'Send campaign'].map(label => (
            <button
              key={label}
              onClick={() => onFakeAction(`${label} — works on your real leads in the full app`)}
              style={{
                padding: '6px 12px', borderRadius: 'var(--radius-pill)',
                border: '1px solid var(--color-ink-300)', background: 'var(--color-surface)',
                color: 'var(--color-ink-700)', fontSize: 12, fontWeight: 500, cursor: 'pointer',
              }}
            >
              {label}
            </button>
          ))}
          <button
            onClick={() => setSelected(new Set())}
            style={{ marginLeft: 'auto', padding: '6px 10px', border: 'none', background: 'none', color: 'var(--color-ink-400)', fontSize: 12, cursor: 'pointer' }}
          >
            Clear
          </button>
        </div>
      )}

      {/* List */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {visible.map(lead => (
          <LeadCard
            key={lead.id}
            lead={lead}
            propertyBased
            categories={DEMO_CATEGORIES}
            selected={selected.has(lead.id)}
            onToggleSelect={toggleSelect}
            onClick={l => onOpen(l.id)}
            onStatusChange={onStatusChange}
            persistStatus={false}
          />
        ))}
        {visible.length === 0 && (
          <p style={{ margin: 0, padding: '28px 0', textAlign: 'center', fontSize: 13, color: 'var(--color-ink-400)' }}>
            No leads match — clear the search or grade filter.
          </p>
        )}
      </div>
    </div>
  )
}
