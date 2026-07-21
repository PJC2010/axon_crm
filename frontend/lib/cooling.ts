import type { LeadStatus, ScoreGrade } from './types'

/**
 * Cooling detection for high-grade leads sitting untouched in early stages
 * (UX audit: loss aversion — exclusive leads have a shelf life).
 *
 * Returns whole days since the lead last moved stage, or null when the lead
 * isn't "cooling": only A/B grades in `new`/`contacted` count, and only after
 * a grace period so fresh imports aren't flagged on day one.
 */
export const COOLING_MIN_DAYS = 5
export const COOLING_URGENT_DAYS = 10

const COOLING_STAGES = new Set<LeadStatus>(['new', 'contacted'])
const COOLING_GRADES = new Set<string>(['A', 'B'])

export function coolingDays(
  grade: ScoreGrade | string | null | undefined,
  status: LeadStatus | string,
  stageMovedAt: string | null | undefined,
  createdAt?: string | null,
): number | null {
  if (!grade || !COOLING_GRADES.has(grade)) return null
  if (!COOLING_STAGES.has(status as LeadStatus)) return null
  const since = stageMovedAt ?? createdAt
  if (!since) return null
  const ms = Date.now() - new Date(since).getTime()
  if (!Number.isFinite(ms) || ms <= 0) return null
  const days = Math.floor(ms / 86_400_000)
  return days >= COOLING_MIN_DAYS ? days : null
}
