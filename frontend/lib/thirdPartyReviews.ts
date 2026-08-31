/**
 * Third-party review badges for the landing page (audit D3.5).
 *
 * The reviews section in LandingContent renders nothing while this list is
 * empty — the same never-fabricate contract as lib/testimonials.ts. To light
 * it up: create the free G2 (and/or Capterra) profile, collect real reviews,
 * then fill in the entries below. Ratings and counts must match what the
 * platform actually shows; the section links out so anyone can check.
 */
export interface ReviewBadge {
  /** e.g. "G2", "Capterra", "Product Hunt" */
  platform: string
  /** Public profile URL, e.g. https://www.g2.com/products/axon-crm/reviews */
  url: string
  /** e.g. "4.8" — omit until real reviews exist */
  rating?: string
  /** Number of reviews behind the rating */
  count?: number
}

export const REVIEW_BADGES: ReviewBadge[] = [
  // Intentionally empty until a real G2/Capterra profile exists. Example:
  // { platform: 'G2', url: 'https://www.g2.com/products/axon/reviews', rating: '4.8', count: 12 },
]
