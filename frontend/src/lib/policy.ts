/**
 * Loading GET /internal/policy.
 *
 * §A.5: no threshold, cost, guardrail number or version is written into the frontend. The assumptions
 * panel renders the whole payload as the server produced it.
 *
 * Nothing reads an individual value out of it any more: the abuse meter used to take guardrail G3's
 * `block_min_p_abuse` to decide where to turn red, and the meter is now one neutral fill at every value
 * (Phase 9 brief 1.1), so `policyValue` and `blockConfidencePercent` are gone with the band they served.
 */
import { useEffect, useState } from 'react'

import { getPolicyAssumptions, type PolicyAssumptionsResponse } from '../api/client'

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
