/**
 * The "Demonstration assumptions" side panel (B3): read-only, headed by the notice, populated from
 * GET /internal/policy. Every number on it comes from the server, including the guardrail thresholds and
 * the policy fingerprint; nothing here is written into the frontend.
 */
import type { PolicyAssumptionsResponse } from '../api/client'
import { humanise } from '../lib/format'

export function AssumptionsPanel({
  policy,
  open,
  onClose,
}: {
  policy: PolicyAssumptionsResponse | null
  open: boolean
  onClose: () => void
}) {
  if (!open) return null
  return (
    <aside
      data-testid="assumptions-panel"
      role="dialog"
      aria-modal="true"
      aria-label="Demonstration assumptions"
      className="fixed inset-y-0 right-0 z-30 flex w-full max-w-md flex-col border-l border-slate-800 bg-slate-900 shadow-2xl"
    >
      <header className="flex items-start justify-between gap-4 border-b border-slate-800 px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-100">Demonstration assumptions</h2>
          {policy && <p className="mt-1 text-xs text-slate-400">{policy.notice}</p>}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 transition-colors duration-150 hover:bg-slate-800"
        >
          Close
        </button>
      </header>
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {policy === null ? (
          <p className="text-sm text-slate-400">The policy configuration could not be read.</p>
        ) : (
          <>
            <dl className="mb-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
              <dt className="text-slate-500">Policy version</dt>
              <dd className="text-slate-200">{policy.policy_version}</dd>
              <dt className="text-slate-500">Config fingerprint</dt>
              <dd className="break-all font-mono text-slate-300">{policy.policy_config_sha256}</dd>
            </dl>
            {policy.sections.map((section) => (
              <section key={section.section} className="mb-4">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                  {humanise(section.section)}
                </h3>
                <dl className="mt-1.5 divide-y divide-slate-800 border-t border-slate-800">
                  {section.values.map((value) => (
                    <div key={value.key} className="flex items-baseline justify-between gap-4 py-1.5">
                      <dt className="text-xs text-slate-400">{humanise(value.key)}</dt>
                      <dd className="shrink-0 text-xs tabular-nums text-slate-200">
                        {value.money ? value.money.display : String(value.value)}
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>
            ))}
          </>
        )}
      </div>
    </aside>
  )
}
