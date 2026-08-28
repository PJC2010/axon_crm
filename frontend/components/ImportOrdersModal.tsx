'use client'
import { useEffect, useRef, useState } from 'react'
import { Upload, X, Download, FileText, CheckCircle } from 'lucide-react'
import { previewOrderImport, runOrderImport, downloadOrderTemplate } from '@/lib/api'
import type { ImportPreview, ImportResult } from '@/lib/types'

interface Props {
  onImported?: () => void
}

const FIELD_LABELS: Record<string, string> = {
  order_number: 'Order number',
  order_date: 'Order date',
  total: 'Total',
  item_count: 'Item count',
  channel: 'Channel',
  status: 'Status',
  contact_name: 'Customer name',
  contact_email: 'Customer email',
  contact_phone: 'Customer phone',
}

type Step = 'select' | 'map' | 'done'

/**
 * Import a Square/Shopify order export. Each usable row (a sale with a customer
 * email) upserts the customer record and its order, then the account is
 * rescored (retail RFM). Shown only where the `orders` module is enabled.
 */
export function ImportOrdersModal({ onImported }: Props) {
  const [open, setOpen] = useState(false)
  const [step, setStep] = useState<Step>('select')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [defaultChannel, setDefaultChannel] = useState('')
  const [result, setResult] = useState<ImportResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') close() }
    if (open) document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  function close() {
    setOpen(false); setStep('select'); setFile(null); setPreview(null)
    setMapping({}); setResult(null); setError(null); setDefaultChannel('')
  }

  async function handleFile(f: File) {
    setFile(f); setLoading(true); setError(null)
    try {
      const p = await previewOrderImport(f)
      setPreview(p); setMapping({ ...p.mapping }); setStep('map')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not read file')
    } finally {
      setLoading(false)
    }
  }

  function setColumn(header: string, field: string) {
    setMapping(prev => {
      const next = { ...prev }
      if (field) next[header] = field
      else delete next[header]
      return next
    })
  }

  async function handleImport() {
    if (!file) return
    setLoading(true); setError(null)
    try {
      const r = await runOrderImport(file, mapping, { default_channel: defaultChannel.trim() || undefined })
      setResult(r); setStep('done'); onImported?.()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Import failed')
    } finally {
      setLoading(false)
    }
  }

  const fieldOptions = preview
    ? Array.from(new Set([...preview.target_fields, ...Object.values(mapping)]))
    : []

  return (
    <>
      <button onClick={() => setOpen(true)} className="btn-secondary" style={{ fontSize: 13, padding: '5px 12px' }}>
        <Upload size={13} strokeWidth={1.5} />
        Import orders
      </button>

      {open && (
        <>
          <div onClick={close} style={{ position: 'fixed', inset: 0, background: 'var(--scrim)', backdropFilter: 'var(--scrim-blur)', zIndex: 'var(--z-alert)' }} />
          <div
            role="dialog" aria-modal="true" aria-labelledby="order-import-title"
            style={{
              position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%, -50%)',
              zIndex: 'var(--z-alert-surface)', width: 'min(640px, calc(100vw - 32px))', maxHeight: 'calc(100dvh - 64px)',
              display: 'flex', flexDirection: 'column',
              background: 'var(--color-surface)', borderRadius: 'var(--radius-modal)', boxShadow: 'var(--shadow-modal)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '20px 24px 12px' }}>
              <p id="order-import-title" style={{ margin: 0, fontSize: 15, fontWeight: 600, color: 'var(--color-ink-900)' }}>
                Import orders
              </p>
              <button onClick={close} aria-label="Close" style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4, color: 'var(--color-ink-400)', display: 'flex' }}>
                <X size={16} />
              </button>
            </div>

            <div style={{ padding: '0 24px 24px', overflowY: 'auto' }}>
              {error && <p style={{ margin: '0 0 12px', fontSize: 13, color: 'var(--color-danger)' }}>{error}</p>}

              {step === 'select' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  <p style={{ margin: 0, fontSize: 13, color: 'var(--color-ink-500)', lineHeight: 1.5 }}>
                    Upload an order export from Square, Shopify, or a spreadsheet. Each sale is matched
                    to a customer by email (created if new) and added to their purchase history. We
                    auto-detect the columns — adjust them before importing.
                  </p>
                  <input
                    ref={fileInput} type="file" accept=".csv,text/csv" style={{ display: 'none' }}
                    onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f) }}
                  />
                  <button
                    onClick={() => fileInput.current?.click()} disabled={loading}
                    style={{
                      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, padding: '28px',
                      borderRadius: 'var(--radius-card)', border: '1.5px dashed var(--color-ink-200)',
                      background: 'var(--color-paper)', cursor: loading ? 'wait' : 'pointer', color: 'var(--color-ink-500)',
                    }}
                  >
                    <FileText size={22} strokeWidth={1.5} />
                    <span style={{ fontSize: 13 }}>{loading ? 'Reading…' : 'Choose a CSV file'}</span>
                  </button>
                  <button onClick={() => downloadOrderTemplate().catch(() => {})} className="btn-secondary" style={{ alignSelf: 'flex-start', fontSize: 12.5, padding: '5px 11px' }}>
                    <Download size={13} strokeWidth={1.5} />
                    Download template
                  </button>
                </div>
              )}

              {step === 'map' && preview && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  <p style={{ margin: 0, fontSize: 13, color: 'var(--color-ink-500)' }}>
                    {preview.usable_rows} of {preview.total_rows} rows look importable
                    {preview.skip_rows > 0 && ` (${preview.skip_rows} have no total or customer email and will be skipped)`}.
                    Match each column to a field:
                  </p>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 280, overflowY: 'auto' }}>
                    {preview.headers.map(header => (
                      <div key={header} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <span style={{ flex: 1, fontSize: 13, color: 'var(--color-ink-900)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{header}</span>
                        <select
                          value={mapping[header] ?? ''}
                          onChange={e => setColumn(header, e.target.value)}
                          style={{ flex: 1, fontSize: 13, padding: '5px 8px', borderRadius: 'var(--radius-button)', border: '1px solid var(--color-ink-200)', background: 'var(--color-paper)', color: 'var(--color-ink-900)' }}
                        >
                          <option value="">— Don&apos;t import —</option>
                          {fieldOptions.map(f => <option key={f} value={f}>{FIELD_LABELS[f] ?? f}</option>)}
                        </select>
                      </div>
                    ))}
                  </div>

                  <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12, color: 'var(--color-ink-500)', maxWidth: 220 }}>
                    Default channel (optional)
                    <input
                      type="text" value={defaultChannel} onChange={e => setDefaultChannel(e.target.value)}
                      placeholder="e.g. online"
                      style={{ fontSize: 13, padding: '5px 8px', borderRadius: 'var(--radius-button)', border: '1px solid var(--color-ink-200)', background: 'var(--color-paper)', color: 'var(--color-ink-900)' }}
                    />
                  </label>

                  <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
                    <button onClick={() => setStep('select')} className="btn-secondary" disabled={loading}>Back</button>
                    <button
                      onClick={handleImport} disabled={loading || preview.usable_rows === 0}
                      style={{
                        display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 16px',
                        borderRadius: 'var(--radius-button)', border: '1px solid transparent',
                        background: 'var(--color-accent)', color: 'var(--text-on-accent)', fontSize: 13, fontWeight: 500,
                        cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.65 : 1,
                      }}
                    >
                      {loading ? 'Importing…' : `Import ${preview.usable_rows} orders`}
                    </button>
                  </div>
                </div>
              )}

              {step === 'done' && result && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <CheckCircle size={20} color="var(--color-accent)" strokeWidth={1.75} />
                    <p style={{ margin: 0, fontSize: 14, fontWeight: 600, color: 'var(--color-ink-900)' }}>Import complete</p>
                  </div>
                  <p style={{ margin: 0, fontSize: 13, color: 'var(--color-ink-500)' }}>
                    {result.imported} added · {result.updated} updated · {result.skipped} skipped
                    {result.errors.length > 0 && ` · ${result.errors.length} errors`}
                  </p>
                  {result.errors.length > 0 && (
                    <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: 'var(--color-danger)', maxHeight: 120, overflowY: 'auto' }}>
                      {result.errors.slice(0, 10).map((er, i) => <li key={i}>{er}</li>)}
                    </ul>
                  )}
                  <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                    <button onClick={close} className="btn-secondary">Done</button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </>
  )
}
