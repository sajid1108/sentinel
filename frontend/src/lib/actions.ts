/**
 * The four actions, their fixed display order and their §11b colours.
 *
 * The order is fixed so the same position always means the same action on every order (B3): the cost chart
 * never re-sorts by value. Colours are the CSS variables declared in index.css; no component names a colour.
 */
import type { components } from '../api/types'

export type Action = components['schemas']['Action']

export const ACTION_ORDER: readonly Action[] = ['ALLOW', 'PREPAID_ONLY', 'MANUAL_REVIEW', 'BLOCK']

export const ACTION_LABEL: Record<Action, string> = {
  ALLOW: 'Allow',
  PREPAID_ONLY: 'Prepaid only',
  MANUAL_REVIEW: 'Manual review',
  BLOCK: 'Block',
}

/** Paint value for a bar, ring or node. */
export const ACTION_FILL: Record<Action, string> = {
  ALLOW: 'var(--color-allow)',
  PREPAID_ONLY: 'var(--color-prepaid)',
  MANUAL_REVIEW: 'var(--color-review)',
  BLOCK: 'var(--color-block)',
}

/** Text colour for the same action: BLOCK uses the AA text tint (see index.css). */
export const ACTION_TEXT: Record<Action, string> = {
  ALLOW: 'text-allow',
  PREPAID_ONLY: 'text-prepaid',
  MANUAL_REVIEW: 'text-review',
  BLOCK: 'text-block-text',
}

export const ACTION_BORDER: Record<Action, string> = {
  ALLOW: 'border-allow/60',
  PREPAID_ONLY: 'border-prepaid/60',
  MANUAL_REVIEW: 'border-review/60',
  BLOCK: 'border-block/60',
}

export const ACTION_TINT: Record<Action, string> = {
  ALLOW: 'bg-allow/10',
  PREPAID_ONLY: 'bg-prepaid/10',
  MANUAL_REVIEW: 'bg-review/10',
  BLOCK: 'bg-block/10',
}

export const INFEASIBLE_FILL = 'var(--color-infeasible)'

export const STATUS_LABEL: Record<string, string> = {
  AUTO_APPLIED: 'Auto applied',
  PENDING_REVIEW: 'Pending review',
  OVERRIDDEN: 'Overridden',
  APPEAL_OPEN: 'Appeal open',
}

export const OVERRIDE_REASONS: readonly components['schemas']['OverrideRequest']['reason_category'][] = [
  'CUSTOMER_VERIFIED',
  'INDEPENDENT_EVIDENCE_OF_ABUSE',
  'FALSE_POSITIVE_SHARED_IDENTIFIER',
  'POLICY_EXCEPTION',
  'OTHER',
]

export const REASON_LABEL: Record<string, string> = {
  CUSTOMER_VERIFIED: 'Customer verified',
  INDEPENDENT_EVIDENCE_OF_ABUSE: 'Independent evidence of abuse',
  FALSE_POSITIVE_SHARED_IDENTIFIER: 'False positive — shared identifier',
  POLICY_EXCEPTION: 'Policy exception',
  OTHER: 'Other',
}
