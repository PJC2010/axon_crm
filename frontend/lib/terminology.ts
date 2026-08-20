import type { Category } from './types'

// Default (home-services) vocabulary. Mirrors BASE_TERMINOLOGY in
// api/business_types.py. Used as the fallback when the account profile hasn't
// loaded yet or omits a key, so labels are always sensible.
export const DEFAULT_TERMINOLOGY: Record<string, string> = {
  lead: 'Lead',
  leads: 'Leads',
  record: 'Property',
  records: 'Properties',
  jobValue: 'Job value',
  territory: 'Service area',
  category: 'Vertical',
  categories: 'Verticals',
  owner: 'Owner',
  propertySignals: 'Property signals',
  quote: 'Quote',
  contact: 'Contact',
}

export type TerminologyKey = keyof typeof DEFAULT_TERMINOLOGY

// Default category picklist (the 8 home-services verticals) for pre-load / when
// the profile omits categories. Mirrors the home_services preset.
export const DEFAULT_CATEGORIES: Category[] = [
  { value: 'epoxy_flooring', label: 'Epoxy flooring' },
  { value: 'pool_maintenance', label: 'Pool maintenance' },
  { value: 'solar', label: 'Solar' },
  { value: 'roofing', label: 'Roofing' },
  { value: 'hvac', label: 'HVAC' },
  { value: 'fencing', label: 'Fencing' },
  { value: 'landscaping', label: 'Landscaping' },
  { value: 'pressure_washing', label: 'Pressure washing' },
]

/** Build a translator bound to a terminology map, falling back to defaults. */
export function makeT(map?: Record<string, string>): (key: string) => string {
  return (key: string) => (map && map[key]) || DEFAULT_TERMINOLOGY[key] || key
}

/**
 * "1 lead" / "2 leads", with the plural form given rather than derived.
 *
 * The map (and most of the app) wrote `` `lead${n === 1 ? '' : 's'}` ``, which is
 * correct English for exactly the words it was hardcoded with and breaks the
 * moment a term is swapped: `t('record')` is "Property", and "Propert" + "s" is
 * not a word. Terminology already ships singular *and* plural keys for every
 * countable noun — `lead`/`leads`, `record`/`records`, `category`/`categories` —
 * and this is the helper that makes using both of them the easy path.
 *
 * So when the map is translated, `plural(n, 'lead', 'leads')` becomes
 * `plural(n, t('lead').toLowerCase(), t('leads').toLowerCase())` and nothing
 * else has to change. Until then it fixes the latent break without pretending
 * to be a translation pass.
 *
 * The count is localised; 1,024 reads better than 1024 in a card.
 */
export function plural(count: number, one: string, many: string): string {
  return `${count.toLocaleString()} ${count === 1 ? one : many}`
}
