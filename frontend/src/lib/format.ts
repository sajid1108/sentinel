/**
 * The frontend NEVER formats money (§4). It renders the server's `Money.display` strings.
 * This file formats probabilities and timestamps only.
 */

export const NO_SCORE = 'No model score'

/** Below this the page says "<0.1%" rather than rounding a real risk down to zero (§A.3). */
const MIN_SHOWN_PERCENT = 0.1

/**
 * A probability as a percentage with one decimal (§A.3). A value that would round to 0.0 % but is not zero
 * renders as `<0.1%`, so the page never claims a risk is zero when it is not. Null means degraded mode:
 * no score was produced, and none is invented.
 */
export function formatProbability(p: number | null | undefined): string {
  if (p === null || p === undefined) return NO_SCORE
  if (p === 0) return '0%'
  const pct = p * PERCENT
  if (pct < MIN_SHOWN_PERCENT) return `<${MIN_SHOWN_PERCENT}%`
  return `${pct.toFixed(1)}%`
}

const PERCENT = 100

/** A probability as a percentage, clamped to the meter's 0-100 scale. */
export function meterPercent(p: number): number {
  return Math.min(PERCENT, Math.max(0, p * PERCENT))
}

/**
 * Probability points, as reason attributions are reported (§6.5): one decimal, signed. A delta too small
 * to show at that precision reads "+0.0 pp" rather than "-0.0 pp"; the code still fires, and the server's
 * `attribution_note` beneath it explains why the delta is ~0 (#27).
 */
export function formatPoints(pp: number): string {
  const magnitude = Math.abs(pp).toFixed(1)
  const sign = pp < 0 && magnitude !== (0).toFixed(1) ? '−' : '+'
  return `${sign}${magnitude} pp`
}

/**
 * Every time on this dashboard is in the demo's own timezone, not the laptop's.
 *
 * `DEMO_CLOCK` is 2026-09-01T10:30+05:30, and the whole synthetic world is timestamped against that
 * offset. Rendering in the browser's zone made the rehearsal machine's clock settings load-bearing for
 * what a judge reads: an order placed at 10:25 IST showed as 4:55 am in a UTC container (Phase 8 open
 * question 3). The zone is named, and the suffix says which one it is.
 */
const DEMO_TIME_ZONE = 'Asia/Kolkata'
const DEMO_TIME_ZONE_LABEL = 'IST'

export function formatTimestamp(iso: string): string {
  const text = new Date(iso).toLocaleString('en-IN', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: DEMO_TIME_ZONE,
  })
  return `${text} ${DEMO_TIME_ZONE_LABEL}`
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-IN', {
    dateStyle: 'medium',
    timeZone: DEMO_TIME_ZONE,
  })
}

/** A hash prefix for display: the first n characters, as the audit timeline and decision card show them. */
export function hashPrefix(hash: string, n: number): string {
  return hash.slice(0, n)
}

/** Config keys and enum values as sentence-case labels, so no vocabulary is duplicated in the UI. */
export function humanise(key: string): string {
  const words = key.replace(/_inr$/, '').replace(/_/g, ' ').trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}
