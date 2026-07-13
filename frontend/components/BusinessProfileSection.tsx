'use client'
import { useEffect, useState, FormEvent } from 'react'
import { Star } from 'lucide-react'
import { getAccountProfile, updateAccountProfile } from '@/lib/api'

/** Settings card for the org profile: business name + the public review link
 *  (Google/Yelp). The link powers the {{review_link}} merge field — the seeded
 *  "Review request — 2 days after job won" automation stays quietly paused
 *  until this is filled in. */
export function BusinessProfileSection() {
  const [name, setName] = useState('')
  const [reviewLink, setReviewLink] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [note, setNote] = useState<string | null>(null)

  useEffect(() => {
    getAccountProfile()
      .then((p) => {
        setName(p.name || '')
        setReviewLink(p.review_link || '')
        setLoaded(true)
      })
      .catch(() => setLoaded(true))
  }, [])

  async function handleSave(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setNote(null)
    try {
      const p = await updateAccountProfile({ name, review_link: reviewLink })
      setName(p.name || '')
      setReviewLink(p.review_link || '')
      setNote('Saved.')
    } catch (err) {
      setNote(err instanceof Error && err.message.includes('400')
        ? 'Review link must be a full URL (https://…).'
        : 'Could not save — try again.')
    } finally {
      setSaving(false)
    }
  }

  if (!loaded) return null

  return (
    <section>
      <h2 className="t-eyebrow" style={{ marginBottom: 6 }}>Business profile</h2>
      <p style={{ fontSize: 13, color: 'var(--color-ink-400)', margin: '0 0 12px' }}>
        <Star size={12} style={{ verticalAlign: '-2px', marginRight: 4 }} />
        Add your Google review link and Axon automatically asks happy customers for a
        review two days after a job is won. No link, no send — it never texts a broken message.
      </p>
      <form onSubmit={handleSave} style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Business name"
          className="drawer-input"
          style={{ width: 220 }}
          required
        />
        <input
          type="url"
          value={reviewLink}
          onChange={(e) => setReviewLink(e.target.value)}
          placeholder="https://g.page/r/… (your review link)"
          className="drawer-input"
          style={{ flex: 1, minWidth: 260 }}
        />
        <button type="submit" disabled={saving} className="btn-primary">
          {saving ? 'Saving…' : 'Save'}
        </button>
      </form>
      {note && (
        <p style={{ fontSize: 12, marginTop: 8, color: note === 'Saved.' ? 'var(--color-moss)' : 'var(--color-rose)' }}>
          {note}
        </p>
      )}
    </section>
  )
}
