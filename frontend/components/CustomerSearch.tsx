'use client'
import { useEffect, useRef, useState, useCallback } from 'react'
import { Search } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { searchCustomers } from '@/lib/api'
import type { CustomerSearchResult } from '@/lib/types'

/**
 * Universal customer lookup. A compact search box in the top nav that opens a
 * results dropdown; ⌘K / Ctrl+K focuses it from anywhere. Selecting a result
 * deep-links to the customer by their durable account number
 * (/dashboard?customer=C-01001), which the Dashboard resolves and opens in the
 * contact drawer.
 */
export function CustomerSearch() {
  const router = useRouter()
  const inputRef = useRef<HTMLInputElement>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  const [q, setQ] = useState('')
  const [results, setResults] = useState<CustomerSearchResult[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [active, setActive] = useState(0)

  // ⌘K / Ctrl+K focuses the box from anywhere.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        inputRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // Close the dropdown on outside click.
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener('mousedown', onClick)
    return () => window.removeEventListener('mousedown', onClick)
  }, [])

  // Debounced search.
  useEffect(() => {
    const term = q.trim()
    if (!term) { setResults([]); setLoading(false); return }
    setLoading(true)
    const t = setTimeout(() => {
      searchCustomers(term)
        .then(r => { setResults(r); setActive(0); setOpen(true) })
        .catch(() => setResults([]))
        .finally(() => setLoading(false))
    }, 200)
    return () => clearTimeout(t)
  }, [q])

  const select = useCallback((r: CustomerSearchResult) => {
    setOpen(false)
    setQ('')
    setResults([])
    inputRef.current?.blur()
    // Prefer the durable account number; fall back to internal id if absent.
    if (r.account_number) {
      router.push(`/dashboard?customer=${encodeURIComponent(r.account_number)}`)
    } else {
      router.push(`/dashboard?lead=${r.id}`)
    }
  }, [router])

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive(a => Math.min(a + 1, results.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(a => Math.max(a - 1, 0)) }
    else if (e.key === 'Enter' && results[active]) { e.preventDefault(); select(results[active]) }
    else if (e.key === 'Escape') { setOpen(false); inputRef.current?.blur() }
  }

  return (
    <div ref={boxRef} style={{ position: 'relative' }}>
      <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
        <Search
          size={13}
          strokeWidth={1.5}
          style={{ position: 'absolute', left: 9, color: 'var(--color-ink-400)', pointerEvents: 'none' }}
        />
        <input
          ref={inputRef}
          value={q}
          onChange={e => setQ(e.target.value)}
          onFocus={() => { if (results.length) setOpen(true) }}
          onKeyDown={onKeyDown}
          placeholder="Search customers…  ⌘K"
          aria-label="Search customers"
          style={{
            width: 220,
            height: 32,
            padding: '0 10px 0 28px',
            fontSize: 13,
            borderRadius: 'var(--radius-button)',
            border: '1px solid var(--color-ink-200)',
            background: 'var(--color-surface)',
            color: 'var(--color-ink-800)',
            outline: 'none',
          }}
        />
      </div>

      {open && (results.length > 0 || (!loading && q.trim())) && (
        <div
          role="listbox"
          style={{
            position: 'absolute', top: 38, right: 0, zIndex: 30,
            width: 340, maxHeight: 380, overflowY: 'auto',
            background: 'var(--color-surface)',
            border: '1px solid var(--color-ink-200)',
            borderRadius: 'var(--radius-card)',
            boxShadow: 'var(--shadow-pop)',
            padding: 4,
          }}
        >
          {results.length === 0 ? (
            <div style={{ padding: '12px 12px', fontSize: 13, color: 'var(--color-ink-400)' }}>
              No customers match “{q.trim()}”
            </div>
          ) : (
            results.map((r, i) => (
              <button
                key={r.id}
                role="option"
                aria-selected={i === active}
                onMouseEnter={() => setActive(i)}
                onClick={() => select(r)}
                style={{
                  display: 'flex', flexDirection: 'column', gap: 2, width: '100%',
                  padding: '8px 10px', textAlign: 'left', cursor: 'pointer',
                  border: 'none', borderRadius: 'var(--radius-button)',
                  background: i === active ? 'var(--color-ink-100)' : 'transparent',
                  color: 'var(--color-ink-800)',
                }}
              >
                <span style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                  <span style={{ fontSize: 13, fontWeight: 600 }}>
                    {r.contact_name || r.owner_name || r.address || 'Unnamed lead'}
                  </span>
                  {r.account_number && (
                    <span className="tabular" style={{ fontSize: 11, color: 'var(--color-accent-300)' }}>
                      {r.account_number}
                    </span>
                  )}
                </span>
                <span style={{ fontSize: 12, color: 'var(--color-ink-400)' }}>
                  {[r.address, r.city, r.contact_phone].filter(Boolean).join(' · ')}
                </span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}
