/**
 * Reading values out of GET /internal/policy.
 *
 * §A.5: no threshold, cost, guardrail number or version is written into the frontend. Where the page has to
 * know one - the abuse meter turns red at the confidence BLOCK needs - it reads it from here.
 */
import { useEffect, useState } from 'react'

import { getPolicyAssumptions, type PolicyAssumptionsResponse } from '../api/client'

export function policyValue(
  policy: PolicyAssumptionsResponse | null,
  section: string,
  key: string,
): number | null {
  if (policy === null) return null
  const value = policy.sections.find((s) => s.section === section)?.values.find((v) => v.key === key)?.value
  return typeof value === 'number' ? value : null
}

/** The p_abuse at or above which BLOCK is permitted (G3), as a percentage, or null until it is known. */
export function blockConfidencePercent(policy: PolicyAssumptionsResponse | null): number | null {
  const value = policyValue(policy, 'guardrails', 'block_min_p_abuse')
  return value === null ? null : value * PERCENT
}

const PERCENT = 100

/** Loads the policy configuration once per mount. Null while loading, and null if it cannot be read. */
export function usePolicyAssumptions(): PolicyAssumptionsResponse | null {
  const [policy, setPolicy] = useState<PolicyAssumptionsResponse | null>(null)
  useEffect(() => {
    let cancelled = false
    getPolicyAssumptions()
      .then((body) => {
        if (!cancelled) setPolicy(body)
      })
      .catch(() => {
        if (!cancelled) setPolicy(null)
      })
    return () => {
      cancelled = true
    }
  }, [])
  return policy
}
