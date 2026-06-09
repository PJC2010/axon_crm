'use client'
import { useEffect, useRef, useState } from 'react'
import { Upload, X, Download, FileText, CheckCircle } from 'lucide-react'
import { previewContactImport, runContactImport, downloadContactTemplate } from '@/lib/api'
import type { ImportPreview, ImportResult } from '@/lib/types'

interface Props {
  onImported: () => void
}

// Friendly labels for the mapping dropdown. Includes the internal tokens the
// auto-detector may emit (first/last name → contact name, formatted address).
const FIELD_LABELS: Record<string, string> = {
  contact_name: 'Contact name',
  contact_phone: 'Phone',
  contact_email: 'Email',
  owner_name: 'Owner name',
  address: 'Address',
  city: 'City',
  state: 'State',
  zip: 'ZIP',
  estimated_value: 'Estimated value',
  vertical: 'Vertical',
  status: 'Status',
  __first__: 'First name (→ contact name)',
  __last__: 'Last name (→ contact name)',
  __addr_formatted__: 'Full address',
}

const STATUSES = ['new', 'contacted', 'qualified', 'quote_sent', 'won', 'lost', 'not_interested']

type Step = 'select' | 'map' | 'done'

export function ImportContactsModal({ onImported }: Props) {
  const [open, setOpen] = useState(false)
  const [step, setStep] = useState<Step>('select')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [defaultVertical, setDefaultVertical] = useState('')
  const [defaultStatus, setDefaultStatus] = useState('new')
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
    setOpen(false)
    setStep('select')
    setFile(null)
    setPreview(null)
    setMapping({})
    setResult(null)
    setError(null)
    setDefaultVertical('')
    setDefaultStatus('new')
  }

  async function handleFile(f: File) {
    setFile(f)
    setLoading(true)
    setError(null)
    try {
      const p = await previewContactImport(f)
      setPreview(p)
      setMapping({ ...p.mapping })
      setStep('map')
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
    setLoading(true)
    setError(null)
    try {
      const r = await runContactImport(file, mapping, {
        default_vertical: defaultVertical.trim() || undefined,
        default_status: defaultStatus,
      })
      setResult(r)
      setStep('done')
      onImported()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Import failed')
    } finally {
      setLoading(false)
    }
  }

  // Dropdown options: known target fields plus any token values present in the
  // current mapping (so an auto-detected first/last/formatted column isn't lost).
  const fieldOptions = preview
    ? Array.from(new Set([...preview.target_fields, ...Object.values(mapping)]))
    : []

  return (
    <>
      <button onClick={() => setOpen(true)} className="btn-secondary" style={{ fontSize: 13, padding: '5px 12px' }}>
        <Upload size={13} strokeWidth={1.5} />
        Import
      </button>

      {open && (
        <>
          <div
            onClick={close}
            style={{ position: 'fixed', inset: 0, background: 'rgba(22,24,29,0.4)', backdropFilter: 'blur(2px)', zIndex: 300 }}
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="import-title"
            style={{
              position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%, -50%)',
              zIndex: 301, width: 'min(640px, calc(100vw - 32px))', maxHeight: 'calc(100vh - 64px)',
              display: 'flex', flexDirection: 'column',
              background: 'var(--color-surface)', borderRadius: 'var(--radius-modal)',
              boxShadow: 'var(--shadow-modal)',
            }}
          >
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '20px 24px 12px' }}>
              <p id="import-title" style={{ margin: 0, fontSize: 15, fontWeight: 600, color: 'var(--color-ink-900)' }}>
                Import contacts &amp; leads
              </p>
              <button onClick={close} aria-label="Close" style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4, color: 'var(--color-ink-400)', display: 'flex' }}>
                <X size={16} />
              </button>
            </div>

            <div style={{ padding: '0 24px 24px', overflowY: 'auto' }}>
              {error && (
                <p style={{ margin: '0 0 12px', fontSize: 13, color: 'var(--color-danger)' }}>{error}</p>
              )}

              {/* Step 1: choose a file */}
              {step === 'select' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  <p style={{ margin: 0, fontSize: 13, color: 'var(--color-ink-500)', lineHeight: 1.5 }}>
                    Upload a CSV exported from a spreadsheet or Google Contacts. Rows with a
                    property address become leads; rows with just a name, phone, or email become
                    contacts. We auto-detect the columns and you can adjust before importing.
                  </p>
                  <input
                    ref={fileInput}
                    type="file"
                    accept=".csv,text/csv"
                    style={{ display: 'none' }}
                    onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f) }}
                  />
                  <button
                    onClick={() => fileInput.current?.click()}
                    disabled={loading}
                    style={{
                      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8,
                      padding: '28px', borderRadius: 'var(--radius-card)',
                      border: '1.5px dashed var(--color-ink-200)', background: 'var(--color-paper)',
                      cursor: loading ? 'wait' : 'pointer', color: 'var(--color-ink-500)',
                    }}
                  >
                    <FileText size={22} strokeWidth={1.5} />
                    <span style={{ fontSize: 13 }}>{loading ? 'Reading…' : 'Choose a CSV file'}</span>
                  </button>
                  <button
                    onClick={() => downloadContactTemplate().catch(() => {})}
                    className="btn-secondary"
                    style={{ alignSelf: 'flex-start', fontSize: 12.5, padding: '5px 11px' }}
                  >
                    <Download size={13} strokeWidth={1.5} />
                    Download template
                  </button>
                </div>
              )}

              {/* Step 2: review the mapping */}
              {step === 'map' && preview && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  <p style={{ margin: 0, fontSize: 13, color: 'var(--color-ink-500)' }}>
                    {preview.usable_rows} of {preview.total_rows} rows look importable
                    {preview.skip_rows > 0 && ` (${preview.skip_rows} have no address or contact info and will be skipped)`}.
                    Match each column to a field:
                  </p>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 280, overflowY: 'auto' }}>
                    {preview.headers.map(header => (
                      <div key={header} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <span style={{ flex: 1, fontSize: 13, color: 'var(--color-ink-900)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {header}
                        </span>
                        <select
                          value={mapping[header] ?? ''}
                          onChange={e => setColumn(header, e.target.value)}
                          style={{
                            flex: 1, fontSize: 13, padding: '5px 8px',
                            borderRadius: 'var(--radius-button)', border: '1px solid var(--color-ink-200)',
                            background: 'var(--color-paper)', color: 'var(--color-ink-900)',
                          }}
                        >
                          <option value="">— Don&apos;t import —</option>
                          {fieldOptions.map(f => (
                            <option key={f} value={f}>{FIELD_LABELS[f] ?? f}</option>
                          ))}
                        </select>
                      </div>
                    ))}
                  </div>

                  <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                    <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12, color: 'var(--color-ink-500)' }}>
                      Default status
                      <select
                        value={defaultStatus}
                        onChange={e => setDefaultStatus(e.target.value)}
                        style={{ fontSize: 13, padding: '5px 8px', borderRadius: 'var(--radius-button)', border: '1px solid var(--color-ink-200)', background: 'var(--color-paper)', color: 'var(--color-ink-900)' }}
                      >
                        {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
                      </select>
                    </label>
                    <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12, color: 'var(--color-ink-500)' }}>
                      Default vertical (optional)
                      <input
                        type="text"
                        value={defaultVertical}
                        onChange={e => setDefaultVertical(e.target.value)}
                        placeholder="e.g. epoxy_flooring"
                        style={{ fontSize: 13, padding: '5px 8px', borderRadius: 'var(--radius-button)', border: '1px solid var(--color-ink-200)', background: 'var(--color-paper)', color: 'var(--color-ink-900)' }}
                      />
                    </label>
                  </div>

                  <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
                    <button onClick={() => setStep('select')} className="btn-secondary" disabled={loading}>Back</button>
                    <button
                      onClick={handleImport}
                      disabled={loading || preview.usable_rows === 0}
                      style={{
                        display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 16px',
                        borderRadius: 'var(--radius-button)', border: '1px solid transparent',
                        background: 'var(--color-accent)', color: 'white', fontSize: 13, fontWeight: 500,
                        cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.65 : 1,
                      }}
                    >
                      {loading ? 'Importing…' : `Import ${preview.usable_rows} rows`}
                    </button>
                  </div>
                </div>
              )}

              {/* Step 3: summary */}
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
