/* The lead score badge is now the canonical design-system component.
   Re-exported here so existing `./ScoreBadge` imports across the app resolve
   to the single Axon Design System primitive. */
export { ScoreBadge } from './ds/ScoreBadge'
export type { ScoreBadgeProps } from './ds/ScoreBadge'
