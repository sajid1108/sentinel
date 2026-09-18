/**
 * Expected-cost comparison (B3). Four horizontal Recharts bars in the fixed order ALLOW, PREPAID_ONLY,
 * MANUAL_REVIEW, BLOCK - never re-sorted by value, so the same position always means the same action.
 *
 * Bar length is `expected_cost.inr`; the label at the bar end and every tooltip figure is the server's
 * `display` string (§4: the browser never formats money). An action a guardrail removed is hatched
 * `slate-600` and carries a chip per guardrail in `excluded_by`, whose `detail` text comes from the
 * response. If the cost-optimal action is not the selected one, the cost-optimal bar carries a "Lowest
 * cost" marker naming the guardrail that removed it.
 */
import { useState } from 'react'
import { Bar, BarChart, Cell, LabelList, ResponsiveContainer, XAxis, YAxis } from 'recharts'

import type { components } from '../api/types'
import { ACTION_FILL, ACTION_LABEL, ACTION_ORDER, INFEASIBLE_FILL, type Action } from '../lib/actions'
import { Panel } from './Panel'

type ActionCost = components['schemas']['ActionCost']
type GuardrailResult = components['schemas']['GuardrailResult']
type PolicyDecision = components['schemas']['PolicyDecision']

const RULE_LABEL: Record<PolicyDecision['selected_rule'], string> = {
  MIN_EXPECTED_COST: 'minimum expected cost',
  MIN_EXPECTED_COST_WITHIN_GUARDRAILS: 'minimum expected cost within guardrails',
  DEGRADED_MODE_FALLBACK: 'degraded-mode fallback',
}

export const DEGRADED_COST_NOTICE = 'Costs are not computed without a model score (degraded mode).'

/** The §11b hatch for an action a guardrail removed. Declared inline below, in the chart's own <defs>. */
const HATCH_ID = 'sentinel-infeasible-hatch'

type Row = {
  action: Action
  label: string
  cost: ActionCost
  selected: boolean
  costOptimal: boolean
}

function guardrailDetail(guardrails: GuardrailResult[], id: string): string {
  return guardrails.find((g) => g.guardrail_id === id)?.detail ?? id
}

function CostBarLabel(props: { x?: number; y?: number; width?: number; height?: number; index?: number; rows: Row[] }) {
  const { x = 0, y = 0, width = 0, height = 0, index = 0, rows } = props
  const row = rows[index]
  if (!row) return null
  return (
    <text
      x={x + width + 8}
      y={y + height / 2}
      dominantBaseline="middle"
      className="fill-slate-200 text-xs tabular-nums"
    >
      {row.cost.expected_cost.display}
    </text>
  )
}

function Tooltip({ cost }: { cost: ActionCost }) {
  return (
    <div className="pointer-events-none absolute z-20 w-64 rounded border border-slate-700 bg-slate-950 p-3 text-xs shadow-lg">
      <p className="font-semibold text-slate-100">{ACTION_LABEL[cost.action]}</p>
      <dl className="mt-2 space-y-1">
        <div className="flex justify-between gap-3">
          <dt className="text-slate-400">If abusive</dt>
          <dd className="tabular-nums text-slate-200">{cost.abusive_branch.display}</dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt className="text-slate-400">If genuine</dt>
          <dd className="tabular-nums text-slate-200">{cost.genuine_branch.display}</dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt className="text-slate-400">Operational</dt>
          <dd className="tabular-nums text-slate-200">{cost.operational.display}</dd>
        </div>
        <div className="flex justify-between gap-3 border-t border-slate-800 pt-1">
          <dt className="text-slate-300">Expected cost</dt>
          <dd className="tabular-nums text-slate-100">{cost.expected_cost.display}</dd>
        </div>
      </dl>
    </div>
  )
}

export function CostComparison({
  policy,
  degraded,
  onOpenAssumptions,
}: {
  policy: PolicyDecision
  degraded: boolean
  onOpenAssumptions: () => void
}) {
  const [hovered, setHovered] = useState<Action | null>(null)

  if (degraded || policy.costs.length === 0) {
    return (
      <Panel title="Expected cost by action">
        <p data-testid="degraded-cost-notice" className="text-sm text-slate-300">
          {DEGRADED_COST_NOTICE}
        </p>
      </Panel>
    )
  }

  const byAction = new Map(policy.costs.map((c) => [c.action, c]))
  const rows: Row[] = ACTION_ORDER.flatMap((action) => {
    const cost = byAction.get(action)
    return cost
      ? [
          {
            action,
            label: ACTION_LABEL[action],
            cost,
            selected: action === policy.selected_action,
            costOptimal: action === policy.cost_optimal_action,
          },
        ]
      : []
  })
  const chartRows = rows.map((r) => ({ ...r, value: r.cost.expected_cost.inr }))
  const costOptimalDiffers =
    policy.cost_optimal_action !== null && policy.cost_optimal_action !== policy.selected_action
  const hoveredCost = hovered === null ? null : (byAction.get(hovered) ?? null)

  return (
    <Panel
      title="Expected cost by action"
      subtitle={policy.assumptions_notice}
      right={
        <span className="text-xs text-slate-500">
          Policy {policy.policy_version} · {RULE_LABEL[policy.selected_rule]}
        </span>
      }
    >
      <div className="relative" data-testid="cost-chart">
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={chartRows} layout="vertical" margin={{ top: 4, right: 96, bottom: 4, left: 8 }}>
            <defs>
              <pattern
                id={HATCH_ID}
                width="8"
                height="8"
                patternTransform="rotate(45)"
                patternUnits="userSpaceOnUse"
              >
                <rect width="8" height="8" fill={INFEASIBLE_FILL} fillOpacity="0.3" />
                <rect width="4" height="8" fill={INFEASIBLE_FILL} />
              </pattern>
            </defs>
            <XAxis type="number" domain={[0, 'dataMax']} hide />
            <YAxis
              type="category"
              dataKey="label"
              width={110}
              tickLine={false}
              axisLine={false}
              tick={{ fill: '#cbd5e1', fontSize: 12 }}
            />
            <Bar
              dataKey="value"
              isAnimationActive={false}
              barSize={22}
              onMouseEnter={(_: unknown, index: number) => setHovered(chartRows[index]?.action ?? null)}
              onMouseLeave={() => setHovered(null)}
            >
              {chartRows.map((row) => (
                <Cell
                  key={row.action}
                  data-testid={`cost-bar-${row.action}`}
                  fill={row.cost.feasible ? ACTION_FILL[row.action] : `url(#${HATCH_ID})`}
                  fillOpacity={row.cost.feasible && !row.selected ? 0.45 : 1}
                  stroke={row.cost.feasible ? undefined : INFEASIBLE_FILL}
                />
              ))}
              <LabelList dataKey="value" content={<CostBarLabel rows={rows} />} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        {hoveredCost && (
          <div className="absolute right-0 top-0">
            <Tooltip cost={hoveredCost} />
          </div>
        )}
      </div>

      <ul className="mt-3 space-y-2">
        {rows.map((row) => (
          <li
            key={row.action}
            data-testid={`cost-row-${row.action}`}
            className="flex flex-wrap items-center gap-2 text-xs"
            onMouseEnter={() => setHovered(row.action)}
            onMouseLeave={() => setHovered(null)}
          >
            <span className="w-28 shrink-0 text-slate-400">{row.label}</span>
            <span className="tabular-nums text-slate-300">{row.cost.expected_cost.display}</span>
            {row.selected && (
              <span
                data-testid={`selected-tag-${row.action}`}
                className="rounded border border-slate-600 bg-slate-800 px-1.5 py-0.5 font-medium text-slate-100"
              >
                Selected
              </span>
            )}
            {costOptimalDiffers && row.costOptimal && (
              <span
                data-testid="lowest-cost-marker"
                className="rounded border border-slate-700 px-1.5 py-0.5 text-slate-300"
                title={row.cost.excluded_by.map((id) => guardrailDetail(policy.guardrails, id)).join(' ')}
              >
                Lowest cost — removed by {row.cost.excluded_by.join(', ') || 'a guardrail'}
              </span>
            )}
            {!row.cost.feasible && (
              <>
                <span className="hatched inline-block h-3 w-6 rounded-sm border border-slate-700" aria-hidden="true" />
                <span className="text-slate-400">Not permitted:</span>
              </>
            )}
            {row.cost.excluded_by.map((id) => (
              <span
                key={id}
                data-testid={`guardrail-chip-${row.action}-${id}`}
                title={guardrailDetail(policy.guardrails, id)}
                className="cursor-help rounded border border-slate-600 bg-slate-800 px-1.5 py-0.5 font-mono text-slate-200"
              >
                {id}
              </span>
            ))}
          </li>
        ))}
      </ul>

      <p data-testid="policy-explanation" className="mt-4 border-t border-slate-800 pt-3 text-sm text-slate-200">
        {policy.policy_explanation}
      </p>
      <button
        type="button"
        onClick={onOpenAssumptions}
        className="mt-2 text-xs text-slate-400 underline underline-offset-2 transition-colors duration-150 hover:text-slate-200"
      >
        Demonstration assumptions
      </button>
    </Panel>
  )
}
