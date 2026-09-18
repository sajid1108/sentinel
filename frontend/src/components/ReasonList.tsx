/**
 * Evidence and model attribution (B5), kept in two panels because they answer different questions (#27):
 *
 *   Evidence          - facts about this order. They are what guardrails G2/G3 count. Server order:
 *                       evidence strength first, which is how reasons arrive.
 *   Model attribution - what moved the score, the same ABUSE codes sorted by |attribution_pp|.
 *
 * A code whose own ablation delta is ~0 still fires, because the fact is real; it carries the server's
 * `attribution_note` saying the score is already explained by correlated features. Attributions are never
 * summed anywhere: they overlap and are not additive.
 */
import type { components } from '../api/types'
import { formatPoints } from '../lib/format'
import { Panel } from './Panel'

type ReasonCode = components['schemas']['ReasonCode']

const STRENGTH_STYLE: Record<ReasonCode['evidence_strength'], string> = {
  STRONG: 'border-slate-500 text-slate-100',
  MODERATE: 'border-slate-600 text-slate-300',
  WEAK: 'border-slate-700 text-slate-400',
}

export function StrengthTag({ strength }: { strength: ReasonCode['evidence_strength'] }) {
  return (
    <span
      className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${STRENGTH_STYLE[strength]}`}
    >
      {strength.toLowerCase()}
    </span>
  )
}

export function ReasonRow({ reason }: { reason: ReasonCode }) {
  return (
    <li data-testid="reason-row" data-code={reason.code} className="flex gap-3">
      <StrengthTag strength={reason.evidence_strength} />
      <div className="min-w-0">
        <p className="text-sm text-slate-200">{reason.reviewer_text}</p>
        {reason.attribution_pp !== null && (
          <p className="mt-0.5 text-xs text-slate-400">
            <span className="tabular-nums">{formatPoints(reason.attribution_pp)}</span> to the score
          </p>
        )}
        {reason.attribution_note && (
          <p className="mt-0.5 text-xs italic text-slate-500">{reason.attribution_note}</p>
        )}
      </div>
    </li>
  )
}

export function EvidencePanel({
  predictionExplanation,
  reasons,
}: {
  predictionExplanation: string
  reasons: ReasonCode[]
}) {
  const abuse = reasons.filter((r) => r.model === 'ABUSE')
  const increasing = abuse.filter((r) => r.direction === 'INCREASES')
  const mitigating = abuse.filter((r) => r.direction === 'DECREASES')
  return (
    <Panel title="Evidence" subtitle="Facts recorded for this order. These are what the guardrails count.">
      <p data-testid="prediction-explanation" className="text-sm text-slate-100">
        {predictionExplanation}
      </p>
      {increasing.length > 0 && (
        <ul data-testid="evidence-list" className="mt-4 space-y-3">
          {increasing.map((reason) => (
            <ReasonRow key={reason.code} reason={reason} />
          ))}
        </ul>
      )}
      {mitigating.length > 0 && (
        <div className="mt-4 border-t border-slate-800 pt-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Mitigating factors</h3>
          <ul data-testid="mitigating-list" className="mt-2 space-y-3">
            {mitigating.map((reason) => (
              <ReasonRow key={reason.code} reason={reason} />
            ))}
          </ul>
        </div>
      )}
      {abuse.length === 0 && <p className="mt-4 text-sm text-slate-400">No abuse reason codes fired.</p>}
    </Panel>
  )
}

const ATTRIBUTION_CAPTION =
  'What moved the model’s score. Contributions overlap and are not additive.'

export function ModelAttributionPanel({ reasons }: { reasons: ReasonCode[] }) {
  const ranked = reasons
    .filter((r) => r.model === 'ABUSE' && r.attribution_pp !== null)
    .slice()
    .sort((a, b) => Math.abs(b.attribution_pp ?? 0) - Math.abs(a.attribution_pp ?? 0))
  const widest = Math.max(...ranked.map((r) => Math.abs(r.attribution_pp ?? 0)), 1)
  return (
    <Panel title="Model attribution">
      {ranked.length === 0 ? (
        <p className="text-sm text-slate-400">No attributions were computed for this decision.</p>
      ) : (
        <ul data-testid="attribution-list" className="space-y-2">
          {ranked.map((reason) => {
            const pp = reason.attribution_pp ?? 0
            return (
              <li key={reason.code} data-testid="attribution-row" data-code={reason.code}>
                <div className="flex items-baseline justify-between gap-3">
                  <span className="truncate text-xs text-slate-300">{reason.code}</span>
                  <span className="shrink-0 text-xs tabular-nums text-slate-400">{formatPoints(pp)}</span>
                </div>
                <div className="mt-1 h-1.5 w-full rounded-full bg-slate-950">
                  <div
                    className="h-1.5 rounded-full bg-slate-500"
                    style={{ width: `${(Math.abs(pp) / widest) * 100}%` }}
                  />
                </div>
              </li>
            )
          })}
        </ul>
      )}
      <p className="mt-4 text-xs text-slate-400">{ATTRIBUTION_CAPTION}</p>
    </Panel>
  )
}

export { ATTRIBUTION_CAPTION }
