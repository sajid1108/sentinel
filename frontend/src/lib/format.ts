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

export function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString('en-IN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-IN', { dateStyle: 'medium' })
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
