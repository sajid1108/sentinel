/**
 * The policy decision card (B1): what is in effect now, what the system recommended, and the versions that
 * produced it. The two actions are labelled explicitly rather than conflated (#34, 1.3): the badge is the
 * *current* action, and when an override moved it the card says what the system recommended.
 */
import type { components } from '../api/types'
import { STATUS_LABEL, type Action } from '../lib/actions'
import { hashPrefix } from '../lib/format'
import { ActionBadge } from './ActionBadge'

type ScoreOrderResponse = components['schemas']['ScoreOrderResponse']

export const DEGRADED_NOTICE = 'Degraded mode: no model score'

export function PolicyDecisionCard({
  decision,
  currentAction,
  onOverride,
  onAppeal,
  busy,
}: {
  decision: ScoreOrderResponse
  currentAction: Action
  onOverride: () => void
  onAppeal: () => void
  busy: boolean
}) {
  const recommended = decision.policy.selected_action
  const overridden = recommended !== currentAction
  const scores = decision.scores
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">Policy decision</p>
          <div className="mt-1.5">
            <ActionBadge action={currentAction} size="lg" />
          </div>
          {overridden && (
            <p data-testid="system-recommended" className="mt-1.5 text-xs text-slate-400">
              System recommended: {recommended}
            </p>
          )}
          <p className="mt-1.5 text-xs text-slate-400">{STATUS_LABEL[decision.status] ?? decision.status}</p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onOverride}
            disabled={busy}
            className="rounded border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 transition-colors duration-150 hover:bg-slate-700 disabled:opacity-50"
          >
            Override
          </button>
          <button
            type="button"
            onClick={onAppeal}
            disabled={busy}
            className="rounded border border-slate-700 px-3 py-1.5 text-sm text-slate-300 transition-colors duration-150 hover:bg-slate-800 disabled:opacity-50"
          >
            Open appeal
          </button>
        </div>
      </div>

      {decision.degraded_mode && (
        <p
          data-testid="degraded-notice"
          className="mt-3 rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200"
        >
          {DEGRADED_NOTICE}
        </p>
      )}

      <dl className="mt-4 flex flex-wrap gap-x-6 gap-y-1 border-t border-slate-800 pt-3 text-[11px] text-slate-500">
        <div className="flex gap-1.5">
          <dt>Policy</dt>
          <dd className="text-slate-400">{decision.policy.policy_version}</dd>
        </div>
        <div className="flex gap-1.5">
          <dt>Fingerprint</dt>
          <dd className="font-mono text-slate-400">{hashPrefix(decision.policy.policy_config_sha256, 8)}</dd>
        </div>
        <div className="flex gap-1.5">
          <dt>Return model</dt>
          <dd className="font-mono text-slate-400">{scores.return_model_version}</dd>
        </div>
        <div className="flex gap-1.5">
          <dt>Abuse model</dt>
          <dd className="font-mono text-slate-400">{scores.abuse_model_version}</dd>
        </div>
      </dl>
    </div>
  )
}
