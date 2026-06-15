'use client'
import { useEffect, useRef, useState } from 'react'
import { Upload, X, FileText, CheckCircle } from 'lucide-react'
import { previewSocialImport, runSocialImport } from '@/lib/api'
import type { Connection, SocialImportPreview, SocialImportResult } from '@/lib/types'

interface Props {
  connection: Connection
  onClose: () => void
  onImported: () => void
}

const EXPORT_KIND_LABELS: Record<string, string> = {
  business_suite_csv: 'Business Suite insights',
  ads_manager_csv: 'Ads Manager report',
  dyi_json: 'Download Your Information',
}

type Step = 'select' | 'preview' | 'done'

// Upload a Meta export (CSV or JSON) for a connected account. Two-step like the
// contact importer: preview the parsed counts, then commit.
export function ConnectMetaModal({ connection, onClose, onImported }: Props) {
  const [step, setStep] = useState<Step>('select')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<SocialImportPreview | null>(null)
  const [result, setResult] = useState<SocialImportResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  async function handleFile(f: File) {
    setFile(f)
    setLoading(true)
    setError(null)
    try {
      const p = await previewSocialImport(connection.id, f)
      setPreview(p)
      setStep('preview')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not read file')
    } finally {
      setLoading(false)
    }
  }

  async function handleImport() {
    if (!file) return
    setLoading(true)
    setError(null)
    try {
      const r = await runSocialImport(connection.id, file)
      setResult(r)
      setStep('done')
      onImported()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Import failed')
    } finally {
      setLoading(false)
    }
  }

  const totalRows = (preview?.metric_rows ?? 0) + (preview?.post_rows ?? 0)

  return (
    <>
      <div
        onClick={onClose}
        style={{ position: 'fixed', inset: 0, background: 'rgba(22,24,29,0.4)', backdropFilter: 'blur(2px)', zIndex: 300 }}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="connect-meta-title"
        style={{
          position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%, -50%)',
          zIndex: 301, width: 'min(560px, calc(100vw - 32px))', maxHeight: 'calc(100vh - 64px)',
          display: 'flex', flexDirection: 'column',
          background: 'var(--color-surface)', borderRadius: 'var(--radius-modal)',
          boxShadow: 'var(--shadow-modal)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '20px 24px 12px' }}>
          <p id="connect-meta-title" style={{ margin: 0, fontSize: 15, fontWeight: 600, color: 'var(--color-ink-900)' }}>
            Upload {connection.display_name || connection.provider} export
          </p>
          <button onClick={onClose} aria-label="Close" style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4, color: 'var(--color-ink-400)', display: 'flex' }}>
            <X size={16} />
          </button>
        </div>

        <div style={{ padding: '0 24px 24px', overflowY: 'auto' }}>
          {error && <p style={{ margin: '0 0 12px', fontSize: 13, color: 'var(--color-danger)' }}>{error}</p>}

          {step === 'select' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <p style={{ margin: 0, fontSize: 13, color: 'var(--color-ink-500)', lineHeight: 1.5 }}>
                Upload an export from Meta Business Suite (insights or post performance CSV),
                Ads Manager (CSV), or your &ldquo;Download Your Information&rdquo; file (JSON). We
                detect the format automatically and use it to generate marketing insights.
              </p>
              <input
                ref={fileInput}
                type="file"
                accept=".csv,.json,text/csv,application/json"
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
                <span style={{ fontSize: 13 }}>{loading ? 'Reading…' : 'Choose a CSV or JSON file'}</span>
              </button>
            </div>
          )}

          {step === 'preview' && preview && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <p style={{ margin: 0, fontSize: 13, color: 'var(--color-ink-500)', lineHeight: 1.5 }}>
                Detected <strong>{EXPORT_KIND_LABELS[preview.export_kind ?? ''] ?? preview.export_kind ?? 'export'}</strong>.
                We found <strong>{preview.metric_rows}</strong> daily metric row{preview.metric_rows !== 1 ? 's' : ''} and{' '}
                <strong>{preview.post_rows}</strong> post{preview.post_rows !== 1 ? 's' : ''}
                {preview.period_start && preview.period_end
                  ? ` spanning ${preview.period_start} → ${preview.period_end}`
                  : ''}.
              </p>
              {preview.errors.length > 0 && (
                <p style={{ margin: 0, fontSize: 12, color: 'var(--color-gold)' }}>
                  {preview.errors.length} row{preview.errors.length !== 1 ? 's' : ''} couldn&apos;t be read and will be skipped.
                </p>
              )}
              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
                <button onClick={() => setStep('select')} className="btn-secondary" disabled={loading}>Back</button>
                <button
                  onClick={handleImport}
                  disabled={loading || totalRows === 0}
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 16px',
                    borderRadius: 'var(--radius-button)', border: '1px solid transparent',
                    background: 'var(--color-accent)', color: 'white', fontSize: 13, fontWeight: 500,
                    cursor: loading || totalRows === 0 ? 'not-allowed' : 'pointer', opacity: loading ? 0.65 : 1,
                  }}
                >
                  <Upload size={13} strokeWidth={1.6} />
                  {loading ? 'Importing…' : `Import ${totalRows} rows`}
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
                {result.metrics_imported} metrics · {result.posts_imported} posts
                {result.skipped > 0 && ` · ${result.skipped} skipped`}
              </p>
              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <button onClick={onClose} className="btn-secondary">Done</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
