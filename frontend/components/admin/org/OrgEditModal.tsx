'use client'
import { useEffect, useState } from 'react'
import { adminUpdateAccount, getBusinessTypes } from '@/lib/api'
import type { AdminAccountDetail, BusinessTypeInfo } from '@/lib/types'
import { apiErr, ERR, LABEL, Modal } from '../UserModals'

/** Edit the org's name, business type and review link. Changing the business
 *  type does not touch enabled modules — that stays a decision on the plan
 *  card (see the endpoint's docstring). Unchanged fields are diffed away
 *  server-side, so sending all three is fine. */
export function OrgEditModal({ detail, onClose, onSaved }: {
  detail: AdminAccountDetail
  onClose: () => void
  onSaved: () => void
}) {
  const [businessTypes, setBusinessTypes] = useState<BusinessTypeInfo[]>([])
  const [name, setName] = useState(detail.name)
  const [businessType, setBusinessType] = useState(detail.business_type)
  const [reviewLink, setReviewLink] = useState(detail.review_link ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getBusinessTypes().then(setBusinessTypes).catch(() => setBusinessTypes([]))
  }, [])

  async function save(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (!name.trim()) { setError('Organization name is required.'); return }
    setSaving(true)
    try {
      await adminUpdateAccount(detail.id, {
        name: name.trim(),
        business_type: businessType,
        review_link: reviewLink.trim() || null,
      })
      onSaved()
    } catch (err: unknown) {
      setError(apiErr(err, 'Failed to save organization'))
      setSaving(false)
    }
  }

  return (
    <Modal title="Edit organization" onClose={onClose} width={440}>
      <form onSubmit={save} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div>
          <label style={LABEL}>Organization name</label>
          <input className="drawer-input" value={name} onChange={(e) => setName(e.target.value)} autoFocus style={{ width: '100%' }} />
        </div>
        <div>
          <label style={LABEL}>Business type</label>
          <select className="select-field" value={businessType} onChange={(e) => setBusinessType(e.target.value)} style={{ width: '100%' }}>
            {businessTypes.length === 0 && <option value={businessType}>{businessType}</option>}
            {businessTypes.map((b) => <option key={b.key} value={b.key}>{b.label}</option>)}
          </select>
        </div>
        <div>
          <label style={LABEL}>Review link</label>
          <input className="drawer-input" type="url" value={reviewLink} onChange={(e) => setReviewLink(e.target.value)} placeholder="https://g.page/… (blank to clear)" style={{ width: '100%' }} />
        </div>
        <p style={{ margin: 0, fontSize: 12, color: 'var(--color-ink-400)', lineHeight: 1.5 }}>
          Changing the business type switches terminology and picklists immediately. It does
          not change which modules are enabled — adjust those on the plan card.
        </p>
        {error && <p style={ERR}>{error}</p>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
          <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
        </div>
      </form>
    </Modal>
  )
}
