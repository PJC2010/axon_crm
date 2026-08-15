'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Upload, X, Download, FileText, CheckCircle } from 'lucide-react'
import { previewContactImport, runContactImport, downloadContactTemplate } from '@/lib/api'
import type { ImportPreview, ImportResult } from '@/lib/types'

interface Props {
  onImported: () => void
  /** Controlled mode. Pass `open` (and `onOpenChange`) to drive the dialog from
   *  a parent and suppress the built-in trigger button.
   *
   *  The mobile nav needs this: its menu unmounts the moment you tap anything in
   *  it, so a self-contained dialog rendered inside that menu was destroyed by
   *  the same tap that opened it — the Import button appeared to do nothing.
   *  The parent keeps the state and renders the dialog outside the menu. */
  open?: boolean
  onOpenChange?: (open: boolean) => void
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

// iOS and Android file pickers grey out CSV files when the accept list is just
// ".csv,text/csv" — the OS reports them under assorted other types (Files.app
// maps .csv to public.comma-separated-values-text, and a Sheets or Drive export
// on Android commonly arrives as application/vnd.ms-excel or text/plain). Widen
// the list so the file can actually be picked; the server validates the bytes
// regardless of what the picker claims the type is.
const CSV_ACCEPT = [
  '.csv', '.txt',
  'text/csv', 'text/comma-separated-values', 'text/plain',
  'application/csv', 'application/vnd.ms-excel',
].join(',')

type Step = 'select' | 'map' | 'done'

export function ImportContactsModal({ onImported, open: openProp, onOpenChange }: Props) {
  const controlled = openProp !== undefined
  const [openState, setOpenState] = useState(false)
  const open = controlled ? openProp : openState
  const setOpen = useCallback((v: boolean) => {
    if (!controlled) setOpenState(v)
    onOpenChange?.(v)
  }, [controlled, onOpenChange])

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

  // Stable so the Escape listener below always closes the current dialog rather
  // than a snapshot of it from the render that registered the listener.
  const close = useCallback(() => {
    setOpen(false)
    setStep('select')
    setFile(null)
    setPreview(null)
    setMapping({})
    setResult(null)
    setError(null)
    setDefaultVertical('')
    setDefaultStatus('new')
  }, [setOpen])

  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') close() }
    if (open) document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, close])

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

  // Dropdown options: known target fields plus the name-part and formatted-address
  // tokens, so a column the auto-detector missed can still be mapped to one.
  const fieldOptions = preview
    ? Array.from(new Set([
        ...preview.target_fields, ...Object.values(mapping),
        '__first__', '__last__', '__addr_formatted__',
      ]))
    : []

  // A row only imports if it carries one of these, so with none of them mapped
  // every row would be skipped. The server's usable_rows count came from the
  // auto-detected mapping and goes stale as soon as the user edits it, so gate
  // on the live mapping rather than on that number.
  const IDENTIFYING = ['address', '__addr_formatted__', 'contact_email',
                       'contact_phone', 'contact_name', '__first__', '__last__', 'owner_name']
  const mappedFields = Object.values(mapping)
  const canImport = IDENTIFYING.some(f => mappedFields.includes(f))
  const mappingEdited = preview
    ? JSON.stringify(mapping) !== JSON.stringify(preview.mapping)
    : false

  return (
    <>
      {!controlled && (
        <button onClick={() => setOpen(true)} className="btn-secondary" style={{ fontSize: 13, padding: '5px 12px' }}>
          <Upload size={13} strokeWidth={1.5} />
          Import
        </button>
      )}

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
              // dvh, not vh: on mobile Safari 100vh is the URL-bar-less height,
              // so the dialog overflowed the screen and its footer buttons sat
              // under the browser chrome.
              zIndex: 301, width: 'min(640px, calc(100vw - 32px))', maxHeight: 'calc(100dvh - 64px)',
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
                    accept={CSV_ACCEPT}
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
                  {mappingEdited && (
                    <p style={{ margin: '-6px 0 0', fontSize: 12, color: 'var(--color-ink-400)' }}>
                      Counts above reflect the auto-detected columns — the final tally comes from your mapping.
                    </p>
                  )}
                  {!canImport && (
                    <p style={{ margin: '-6px 0 0', fontSize: 12, color: 'var(--color-danger)' }}>
                      Map at least one of address, email, phone, or name — every row is skipped without one.
                    </p>
                  )}

                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 280, overflowY: 'auto' }}>
                    {/* Keyed by index: a CSV may repeat a header name, and a
                        duplicated React key drops rows from the list. */}
                    {preview.headers.map((header, i) => (
                      <div key={`${header}-${i}`} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
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
                      disabled={loading || preview.total_rows === 0 || !canImport}
                      style={{
                        display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 16px',
                        borderRadius: 'var(--radius-button)', border: '1px solid transparent',
                        background: 'var(--color-accent)', color: 'white', fontSize: 13, fontWeight: 500,
                        cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.65 : 1,
                      }}
                    >
                      {loading ? 'Importing…' : mappingEdited ? 'Import' : `Import ${preview.usable_rows} rows`}
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
                    {(result.error_count ?? result.errors.length) > 0 &&
                      ` · ${result.error_count ?? result.errors.length} errors`}
                  </p>
                  {(result.coerced_statuses ?? 0) > 0 && (
                    <p style={{ margin: 0, fontSize: 12, color: 'var(--color-ink-400)' }}>
                      {result.coerced_statuses} row(s) had a status that isn&apos;t one of your pipeline
                      stages — they were set to &ldquo;{defaultStatus}&rdquo; so they show up on the board.
                    </p>
                  )}
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
