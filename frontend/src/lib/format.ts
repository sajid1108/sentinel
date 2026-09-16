/**
 * The frontend NEVER formats money. It renders server-provided display strings.
 * This file contains only non-monetary formatting utilities.
 */

export function formatProbability(p: number): string {
  return `${(p * 100).toFixed(1)}%`
}

export function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString('en-IN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}
