import { describe, it, expect } from 'vitest'
import { plural, makeT, DEFAULT_TERMINOLOGY } from './terminology'

describe('plural', () => {
  it('picks the form by count', () => {
    expect(plural(1, 'lead', 'leads')).toBe('1 lead')
    expect(plural(0, 'lead', 'leads')).toBe('0 leads')
    expect(plural(2, 'lead', 'leads')).toBe('2 leads')
  })

  it('localises the count', () => {
    expect(plural(1024, 'lead', 'leads')).toBe('1,024 leads')
  })

  it('handles a plural that is not the singular plus s', () => {
    // The whole reason this exists: `"Propert" + "s"` is what the old
    // concatenation produced once a term was swapped.
    const t = makeT({ record: 'Property', records: 'Properties' })
    expect(plural(3, t('record').toLowerCase(), t('records').toLowerCase()))
      .toBe('3 properties')
  })
})

describe('terminology keys', () => {
  it('ships a plural for every countable noun the map can print', () => {
    // A missing plural key is invisible until something counts with it.
    for (const [one, many] of [['lead', 'leads'], ['record', 'records'], ['category', 'categories']]) {
      expect(DEFAULT_TERMINOLOGY[one]).toBeTruthy()
      expect(DEFAULT_TERMINOLOGY[many]).toBeTruthy()
    }
  })
})
