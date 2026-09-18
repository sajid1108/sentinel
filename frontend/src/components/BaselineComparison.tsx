/**
 * "How the baselines would decide" (B6). The §9.5 contrast: RULE_BASED blocks Demo 1, a loyal returner,
 * and only reviews Demo 2, the ring member, with no reason behind it. Comparison only - Sentinel's action
 * is the one in the decision card.
 */
import type { components } from '../api/types'
import { ActionBadge } from './ActionBadge'
import { Panel } from './Panel'

const STRATEGY_LABEL: Record<components['schemas']['BaselineOutcome']['strategy'], string> = {
  FIXED_THRESHOLD: 'Fixed threshold',
  RULE_BASED: 'Rule based',
}

export const BASELINE_CAPTION = 'For comparison only. Sentinel\u2019s action is the one above.'

export function BaselineComparison({
  baselines,
}: {
  baselines: components['schemas']['BaselineOutcome'][]
}) {
  return (
    <Panel title="How the baselines would decide">
      {baselines.length === 0 ? (
        <p className="text-sm text-slate-400">No baseline could be computed for this decision.</p>
      ) : (
        <ul data-testid="baselines" className="space-y-3">
          {baselines.map((baseline) => (
            <li key={baseline.strategy} data-testid={`baseline-${baseline.strategy}`}>
              <div className="flex items-center gap-2">
                <span className="text-xs uppercase tracking-wide text-slate-500">
                  {STRATEGY_LABEL[baseline.strategy]}
                </span>
                <ActionBadge action={baseline.action} size="sm" />
              </div>
              <p className="mt-0.5 text-xs text-slate-400">{baseline.rule_fired}</p>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-4 text-xs text-slate-400">{BASELINE_CAPTION}</p>
    </Panel>
  )
}
