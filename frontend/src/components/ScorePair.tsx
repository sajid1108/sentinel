/**
 * The two probability cards (B2). They are two components with two independent 0-100 % meters and they are
 * never merged, averaged, summed or placed on a shared scale: §Non-negotiable 2 and §A.4. The return card
 * is `sky-400` and never red, whatever the value, because a high return rate is not risk (§C2/G1).
 */
import type { components } from '../api/types'
import { ACTION_FILL } from '../lib/actions'
import { NO_SCORE, formatProbability, meterPercent } from '../lib/format'
import { Panel } from './Panel'
import { ReasonRow } from './ReasonList'

type ReasonCode = components['schemas']['ReasonCode']

const RETURN_CAPTION = 'Operational context — not used for action selection.'

export { RETURN_CAPTION }

/** A 0-100 % meter. Each card owns one; they never share a scale. */
function Meter({
  value,
  fill,
  label,
  ghost,
  testId,
}: {
  value: number
  fill: string
  label: string
  ghost?: { value: number; label: string }
  testId: string
}) {
  return (
    <div
      data-testid={testId}
      role="meter"
      aria-label={label}
      aria-valuenow={Math.round(value * 1000) / 10}
      aria-valuemin={0}
      aria-valuemax={100}
      className="relative mt-3 h-3 w-full rounded-full border border-slate-800 bg-slate-950"
    >
      <div
        data-testid={`${testId}-fill`}
        className="absolute inset-y-0 left-0 rounded-full"
        style={{ width: `${meterPercent(value)}%`, backgroundColor: fill }}
      />
      {ghost && (
        <div
          data-testid={`${testId}-ghost`}
          title={ghost.label}
          aria-label={ghost.label}
          className="absolute -top-1 h-5 w-0.5 bg-slate-400"
          style={{ left: `${meterPercent(ghost.value)}%` }}
        />
      )}
      <div className="pointer-events-none absolute -bottom-4 flex w-full justify-between text-[10px] text-slate-600">
        <span>0%</span>
        <span>100%</span>
      </div>
    </div>
  )
}

/**
 * Neutral below the halfway mark, MANUAL_REVIEW amber above it, BLOCK red from the confidence BLOCK
 * actually needs (B2). That last figure is guardrail G3's `block_min_p_abuse`, so it is read from the
 * policy configuration, never written here; until it is known the meter makes no colour claim beyond amber.
 */
const AMBER_FROM_PERCENT = 50

function abuseFill(p: number, blockFromPercent: number | null): string {
  const pct = meterPercent(p)
  if (blockFromPercent !== null && pct >= blockFromPercent) return ACTION_FILL.BLOCK
  if (pct >= AMBER_FROM_PERCENT) return ACTION_FILL.MANUAL_REVIEW
  return 'var(--color-neutral-meter)'
}

export function ReturnScoreCard({
  pReturn,
  reasons,
}: {
  pReturn: number | null
  reasons: ReasonCode[]
}) {
  return (
    <Panel title="Return probability">
      <div data-testid="return-score-card">
        <p className="text-4xl font-semibold tabular-nums text-return">{formatProbability(pReturn)}</p>
        {pReturn !== null && (
          <Meter value={pReturn} fill="var(--color-return)" label="Return probability" testId="return-meter" />
        )}
        <p className="mt-6 text-xs text-slate-400">{RETURN_CAPTION}</p>
        {reasons.length > 0 && (
          <ul className="mt-3 space-y-2 border-t border-slate-800 pt-3">
            {reasons.map((reason) => (
              <ReasonRow key={reason.code} reason={reason} />
            ))}
          </ul>
        )}
      </div>
    </Panel>
  )
}

export function AbuseScoreCard({
  pAbuse,
  withoutGraph,
  blockFromPercent,
}: {
  pAbuse: number | null
  withoutGraph: number | null
  blockFromPercent: number | null
}) {
  const counterfactual =
    withoutGraph === null
      ? null
      : `Without relationship evidence: ${formatProbability(withoutGraph)} (counterfactual: relationship features set to typical values)`
  return (
    <Panel title="Abuse probability">
      <div data-testid="abuse-score-card">
        <p className="text-4xl font-semibold tabular-nums text-slate-100">{formatProbability(pAbuse)}</p>
        {pAbuse !== null && (
          <Meter
            value={pAbuse}
            fill={abuseFill(pAbuse, blockFromPercent)}
            label="Abuse probability"
            testId="abuse-meter"
            ghost={
              withoutGraph === null || counterfactual === null
                ? undefined
                : { value: withoutGraph, label: counterfactual }
            }
          />
        )}
        <p className="mt-6 text-xs text-slate-400">
          {counterfactual ?? (pAbuse === null ? NO_SCORE : 'No counterfactual was computed for this decision.')}
        </p>
      </div>
    </Panel>
  )
}
