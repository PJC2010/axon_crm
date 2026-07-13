'use client'
import { Download } from 'lucide-react'
import { qboExportUrl } from '@/lib/api'

function download(kind: 'invoices' | 'expenses') {
  const a = document.createElement('a')
  a.href = qboExportUrl(kind)
  a.download = `qbo_${kind}.csv`
  a.click()
}

/** Settings card: one-way exports in QuickBooks Online's own import formats —
 *  the "your bookkeeper can leave anytime" guarantee (invoices as QBO's
 *  invoice-import CSV, expenses as the 3-column bank-transaction CSV). */
export function QuickBooksExportSection() {
  return (
    <section>
      <h2 className="t-eyebrow" style={{ marginBottom: 6 }}>QuickBooks export</h2>
      <p style={{ fontSize: 13, color: 'var(--color-ink-400)', margin: '0 0 12px' }}>
        Download your books in QuickBooks Online&apos;s import formats. Invoices import via
        Settings → Import data → Invoices; expenses import like a bank statement
        (Transactions → Upload from file).
      </p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button onClick={() => download('invoices')} className="btn-secondary" style={{ fontSize: 13, padding: '6px 14px', display: 'flex', alignItems: 'center', gap: 6 }}>
          <Download size={13} strokeWidth={1.5} /> Invoices (QBO format)
        </button>
        <button onClick={() => download('expenses')} className="btn-secondary" style={{ fontSize: 13, padding: '6px 14px', display: 'flex', alignItems: 'center', gap: 6 }}>
          <Download size={13} strokeWidth={1.5} /> Expenses (QBO format)
        </button>
      </div>
    </section>
  )
}
