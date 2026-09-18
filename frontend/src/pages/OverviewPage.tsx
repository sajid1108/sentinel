/**
 * Overview: route `/` (§12 phase 10, brief §D).
 *
 * Two sections that are never mixed, because they answer different questions from different sources
 * (§Appendix A, C8):
 *
 *   Decision activity  - counts from this database. No labels exist for live decisions, so nothing here
 *                        is an effectiveness claim, and the avoided cost is the model's own estimate.
 *   Synthetic backtest - realized cost against synthetic labels on the held-out TEST split.
 *
 * No row of the backtest is highlighted, coloured or marked "best". The tuned fixed-threshold baseline
 * has a lower realized cost than Sentinel and the table says so plainly; the trade is the demo script's
 * to explain, not the UI's to editorialise.
 *
 * Minimal by design (§D): plain figures, no animated counters, no charts. The calibration chart, the
 * sensitivity sweep and the cohort tables are Phase 11.
 */
import { useEffect, useState } from 'react'

import {
  ApiError,
  getHealth,
  getMetrics,
  type HealthResponse,
  type MetricsResponse,
} from '../api/client'
import { Panel, Skeleton } from '../components/Panel'
import { ACTION_LABEL, ACTION_ORDER } from '../lib/actions'
import { formatOneDecimal, formatProbability } from '../lib/format'

type Backtest = MetricsResponse['backtest'][number]
type Strategy = Backtest['strategy']

/** Fixed order, so the same row is always in the same place (§D2). */
const STRATEGY_ORDER: readonly Strategy[] = ['SENTINEL', 'FIXED_THRESHOLD', 'RULE_BASED', 'ALLOW_ALL']

const STRATEGY_LABEL: Record<Strategy, string> = {
  SENTINEL: 'Sentinel',
  FIXED_THRESHOLD: 'Fixed threshold',
  RULE_BASED: 'Rule based',
  ALLOW_ALL: 'Allow all',
}

export const ACTIVITY_LABEL =
  'Decision activity: decisions in this database, counted by system recommendation'

export const BACKTEST_LABEL =
  'Synthetic backtest: realized cost against synthetic labels on the held-out TEST split. ' +
  'Monetary values are demonstration assumptions'

export const COST_AVOIDED_LABEL = 'Model-estimated cost avoided (estimate, not realized)'

/** Every `StrategyBacktest` field is a column (§D2). Money renders from `display`, rates as percentages. */
const COLUMNS: {
  key: string
  label: string
  value: (row: Backtest) => string
}[] = [
  { key: 'realized_cost_per_1000', label: 'Realized cost / 1,000', value: (r) => r.realized_cost_per_1000.display },
  { key: 'abuse_loss_prevented', label: 'Abuse loss prevented', value: (r) => r.abuse_loss_prevented.display },
  { key: 'genuine_block_rate', label: 'Genuine block rate', value: (r) => formatProbability(r.genuine_block_rate) },
  { key: 'customer_friction_rate', label: 'Customer friction rate', value: (r) => formatProbability(r.customer_friction_rate) },
  { key: 'manual_reviews_per_1000', label: 'Manual reviews / 1,000', value: (r) => formatOneDecimal(r.manual_reviews_per_1000) },
  { key: 'cost_per_detected_abuse', label: 'Cost per detected abuse', value: (r) => r.cost_per_detected_abuse.display },
  { key: 'revenue_preserved', label: 'Revenue preserved', value: (r) => r.revenue_preserved.display },
  { key: 'precision_block', label: 'Block precision', value: (r) => formatProbability(r.precision_block) },
  { key: 'recall_intercepted', label: 'Recall intercepted', value: (r) => formatProbability(r.recall_intercepted) },
]

function Figure({ label, value, testId }: { label: string; value: string; testId: string }) {
  return (
    <div data-testid={testId}>
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-xl font-semibold tabular-nums text-slate-100">{value}</p>
    </div>
  )
}

function ActivitySection({ activity }: { activity: MetricsResponse['activity'] }) {
  return (
    <Panel title="Decision activity" subtitle={<span data-testid="activity-label">{ACTIVITY_LABEL}</span>}>
      <div data-testid="activity-figures" className="flex flex-wrap gap-x-10 gap-y-4">
        <Figure label="Orders evaluated" value={String(activity.orders_evaluated)} testId="orders-evaluated" />
        <Figure label="Friction orders" value={String(activity.friction_orders)} testId="friction-orders" />
        <Figure label="Manual review volume" value={String(activity.manual_review_volume)} testId="manual-review-volume" />
        <Figure label="Override rate" value={formatProbability(activity.override_rate)} testId="override-rate" />
        <Figure
          label={COST_AVOIDED_LABEL}
          value={activity.model_estimated_cost_avoided.display}
          testId="cost-avoided"
        />
        <Figure
          label="Weak-evidence decisions"
          value={String(activity.weak_evidence_decisions)}
          testId="weak-evidence-decisions"
        />
      </div>

      <div data-testid="action-distribution" className="mt-5 border-t border-slate-800 pt-3">
        <p className="text-xs uppercase tracking-wide text-slate-500">Action distribution</p>
        <ul className="mt-1.5 flex flex-wrap gap-x-8 gap-y-1 text-sm">
          {ACTION_ORDER.map((action) => (
            <li key={action} data-testid={`distribution-${action}`} className="flex gap-2">
              <span className="text-slate-400">{ACTION_LABEL[action]}</span>
              <span className="tabular-nums text-slate-100">{activity.action_distribution[action] ?? 0}</span>
            </li>
          ))}
        </ul>
      </div>
    </Panel>
  )
}

function BacktestSection({
  backtest,
  coldStartRecall,
  policyVersion,
}: {
  backtest: Backtest[]
  coldStartRecall: number
  policyVersion: string | null
}) {
  const byStrategy = new Map(backtest.map((row) => [row.strategy, row]))
  const rows = STRATEGY_ORDER.map((strategy) => byStrategy.get(strategy)).filter(
    (row): row is Backtest => row !== undefined,
  )
  return (
    <Panel
      title="Synthetic backtest"
      subtitle={
        <span data-testid="backtest-label">
          {BACKTEST_LABEL}
          {policyVersion === null ? '' : ` (policy ${policyVersion})`}.
        </span>
      }
    >
      <div className="overflow-x-auto">
        <table data-testid="backtest-table" className="w-full text-left text-xs">
          <thead>
            <tr className="text-[11px] uppercase tracking-wide text-slate-500">
              <th scope="col" className="px-3 pb-2 font-medium">
                Strategy
              </th>
              {COLUMNS.map((column) => (
                <th key={column.key} scope="col" className="px-3 pb-2 text-right font-medium">
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              // No row is highlighted, coloured or marked "best": every row carries the same classes.
              <tr
                key={row.strategy}
                data-testid="backtest-row"
                data-strategy={row.strategy}
                className="border-t border-slate-800"
              >
                <th scope="row" className="px-3 py-2 text-left font-medium text-slate-200">
                  {STRATEGY_LABEL[row.strategy]}
                </th>
                {COLUMNS.map((column) => (
                  <td
                    key={column.key}
                    data-column={column.key}
                    className="px-3 py-2 text-right tabular-nums text-slate-300"
                  >
                    {column.value(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p data-testid="cold-start-recall" className="mt-4 border-t border-slate-800 pt-3 text-sm text-slate-300">
        Cold-start ring (R3, unseen in training): recall {formatProbability(coldStartRecall)}
      </p>
    </Panel>
  )
}

export function OverviewPage() {
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setError(null)
    setMetrics(null)
    getMetrics()
      .then(setMetrics)
      .catch((err: unknown) =>
        setError(err instanceof ApiError ? err.detail : 'The metrics could not be loaded.'),
      )
  }

  useEffect(load, [])

  useEffect(() => {
    let cancelled = false
    getHealth()
      .then((body) => {
        if (!cancelled) setHealth(body)
      })
      .catch(() => {
        if (!cancelled) setHealth(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="min-w-0 space-y-4 p-6">
      <h1 className="text-xl font-semibold text-slate-100">Overview</h1>

      {error !== null && (
        <Panel title="Overview">
          <div data-testid="overview-error">
            <p className="text-sm text-error">{error}</p>
            <button
              type="button"
              data-testid="overview-retry"
              onClick={load}
              className="mt-3 rounded border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 transition-colors duration-150 hover:bg-slate-700"
            >
              Retry
            </button>
          </div>
        </Panel>
      )}

      {error === null && metrics === null && (
        <div data-testid="overview-skeleton" className="space-y-4">
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      )}

      {metrics !== null && (
        <>
          <ActivitySection activity={metrics.activity} />
          <BacktestSection
            backtest={metrics.backtest}
            coldStartRecall={metrics.cold_start_ring_recall}
            policyVersion={health?.policy_version ?? null}
          />
        </>
      )}
    </div>
  )
}

export default OverviewPage
