/**
 * The review queue: route `/queue` (§12 phase 9, brief §A-C).
 *
 * The two probabilities are two columns with two headings and are never combined into one score
 * (§Non-negotiable 2). The return column is never red: a customer who returns often is not a risk
 * verdict (§C2/G1, DESIGN.md §2). Money is the server's `display` string, always.
 *
 * The counts row and the action filter both say "current action (after review)" out loud, because the
 * queue counts what is in effect now while `/metrics` counts what the system recommended (#34, 1.3).
 * Two different questions, labelled rather than reconciled.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { ApiError, getQueue, type QueueItem, type QueueResponse } from '../api/client'
import { ActionBadge } from '../components/ActionBadge'
import { Panel, Skeleton } from '../components/Panel'
import { SimulateCheckout } from '../components/SimulateCheckout'
import { TryAnOrder } from '../components/TryAnOrder'
import { ACTION_LABEL, ACTION_ORDER, type Action } from '../lib/actions'
import { NO_SCORE, formatProbability, formatTimestamp } from '../lib/format'
import {
  DEFAULT_FILTERS,
  GRAPH_EVIDENCE_LABEL,
  GRAPH_EVIDENCE_VALUES,
  PAGE_SIZE,
  SORT_LABEL,
  SORT_VALUES,
  SOURCE_LABEL,
  SOURCE_VALUES,
  STATUS_LABEL_QUEUE,
  STATUS_VALUES,
  apiQueryFromFilters,
  filtersFromQuery,
  hasActiveFilters,
  queryFromFilters,
  type QueueFilterState,
} from '../lib/queue'

export const EMPTY_MESSAGE = 'No orders match these filters'
export const ACTION_FILTER_LABEL = 'Current action (after review)'
export const COUNTS_LABEL = 'Decisions by current action (after review)'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'ready'; queue: QueueResponse }
  | { kind: 'error'; message: string }

const COLUMNS = [
  'Order',
  'Scored at',
  'Order value',
  'Return probability',
  'Abuse probability',
  'Recommended action',
  'Current action',
  'Status',
  'Graph evidence',
  'Source',
] as const

function QueueSkeleton() {
  return (
    <div data-testid="queue-skeleton" className="space-y-2">
      {Array.from({ length: 8 }, (_, i) => (
        <Skeleton key={i} className="h-8 w-full" />
      ))}
    </div>
  )
}

function Select<T extends string>({
  label,
  value,
  options,
  labels,
  onChange,
  anyLabel,
  testId,
}: {
  label: string
  value: T | null
  options: readonly T[]
  labels: Record<T, string>
  onChange: (value: T | null) => void
  anyLabel?: string
  testId: string
}) {
  return (
    <label className="flex flex-col gap-1 text-xs text-slate-400">
      {label}
      <select
        data-testid={testId}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value === '' ? null : (e.target.value as T))}
        className="rounded border border-slate-600 bg-slate-950 px-2 py-1.5 text-sm text-slate-100"
      >
        {anyLabel !== undefined && <option value="">{anyLabel}</option>}
        {options.map((option) => (
          <option key={option} value={option}>
            {labels[option]}
          </option>
        ))}
      </select>
    </label>
  )
}

/** A probability cell. Degraded decisions carry no score and none is invented (#14). */
function ProbabilityCell({ value, testId }: { value: number | null; testId: string }) {
  return (
    <td
      data-testid={testId}
      className={`px-3 py-2 text-right tabular-nums ${value === null ? 'text-slate-500' : 'text-slate-200'}`}
    >
      {value === null ? NO_SCORE : formatProbability(value)}
    </td>
  )
}

function Row({ item }: { item: QueueItem }) {
  return (
    <tr data-testid="queue-row" data-order-id={item.order_id} className="border-t border-slate-800">
      <td className="px-3 py-2">
        <Link
          to={`/orders/${encodeURIComponent(item.order_id)}`}
          className="font-mono text-xs text-slate-100 underline underline-offset-2"
        >
          {item.order_id}
        </Link>
      </td>
      <td className="px-3 py-2 text-slate-400">{formatTimestamp(item.scored_at)}</td>
      <td className="px-3 py-2 text-right tabular-nums text-slate-200">{item.order_value.display}</td>
      {/* Two columns, two headings, never one score. The return column carries no risk colour. */}
      <ProbabilityCell value={item.p_return} testId="queue-p-return" />
      <ProbabilityCell value={item.p_abuse} testId="queue-p-abuse" />
      <td className="px-3 py-2">
        <ActionBadge action={item.recommended_action} size="sm" />
      </td>
      <td className="px-3 py-2">
        <ActionBadge action={item.current_action} size="sm" />
      </td>
      <td className="px-3 py-2 text-slate-400">{STATUS_LABEL_QUEUE[item.status] ?? item.status}</td>
      <td className="px-3 py-2 text-slate-400">{item.graph_risk_summary}</td>
      <td className="px-3 py-2 text-slate-400">{SOURCE_LABEL[item.source] ?? item.source}</td>
    </tr>
  )
}

export function QueuePage() {
  const [params, setParams] = useSearchParams()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const filters = useMemo(() => filtersFromQuery(params), [params])
  const query = apiQueryFromFilters(filters)

  const load = useCallback(() => {
    setState({ kind: 'loading' })
    getQueue(query)
      .then((queue) => setState({ kind: 'ready', queue }))
      .catch((err: unknown) =>
        setState({
          kind: 'error',
          message: err instanceof ApiError ? err.detail : 'The queue could not be loaded.',
        }),
      )
  }, [query])

  useEffect(() => {
    load()
  }, [load])

  /** Any filter change resets the page: page 3 of the old filter means nothing under the new one. */
  const update = (patch: Partial<QueueFilterState>) => {
    const next = { ...filters, ...patch }
    if (!('offset' in patch)) next.offset = 0
    setParams(new URLSearchParams(queryFromFilters(next)), { replace: false })
  }

  const clear = () => setParams(new URLSearchParams(), { replace: false })

  const queue = state.kind === 'ready' ? state.queue : null
  const first = queue === null || queue.items.length === 0 ? 0 : filters.offset + 1
  const last = queue === null ? 0 : filters.offset + queue.items.length

  return (
    <div className="min-w-0 space-y-4 p-6">
      <h1 className="text-xl font-semibold text-slate-100">Review queue</h1>

      {/* Phase 9 §B/§C and Phase 10 §B, side by side — only when DEMO_MODE is on; both render nothing otherwise. */}
      <div className="grid min-w-0 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <SimulateCheckout onReset={load} />
        <TryAnOrder onPlaced={load} />
      </div>

      <Panel title="Filters">
        <div className="flex flex-wrap items-end gap-4">
          <Select
            label={ACTION_FILTER_LABEL}
            testId="filter-action"
            value={filters.action}
            options={ACTION_ORDER as readonly Action[]}
            labels={ACTION_LABEL}
            anyLabel="Any"
            onChange={(action) => update({ action })}
          />
          <Select
            label="Status"
            testId="filter-status"
            value={filters.status}
            options={STATUS_VALUES}
            labels={STATUS_LABEL_QUEUE}
            anyLabel="Any"
            onChange={(status) => update({ status })}
          />
          <Select
            label="Source"
            testId="filter-source"
            value={filters.source}
            options={SOURCE_VALUES}
            labels={SOURCE_LABEL}
            anyLabel="Any"
            onChange={(source) => update({ source })}
          />
          <Select
            label="Graph evidence"
            testId="filter-graph-evidence"
            value={filters.graph_evidence}
            options={GRAPH_EVIDENCE_VALUES}
            labels={GRAPH_EVIDENCE_LABEL}
            onChange={(graph_evidence) =>
              update({ graph_evidence: graph_evidence ?? DEFAULT_FILTERS.graph_evidence })
            }
          />
          <Select
            label="Sort"
            testId="filter-sort"
            value={filters.sort}
            options={SORT_VALUES}
            labels={SORT_LABEL}
            onChange={(sort) => update({ sort: sort ?? DEFAULT_FILTERS.sort })}
          />
          {hasActiveFilters(filters) && (
            <button
              type="button"
              data-testid="clear-filters"
              onClick={clear}
              className="rounded border border-slate-700 px-3 py-1.5 text-sm text-slate-300 transition-colors duration-150 hover:bg-slate-800"
            >
              Clear filters
            </button>
          )}
        </div>

        {queue !== null && (
          <div data-testid="counts-by-action" className="mt-4 border-t border-slate-800 pt-3">
            <p className="text-xs uppercase tracking-wide text-slate-500">{COUNTS_LABEL}</p>
            <ul className="mt-1.5 flex flex-wrap gap-x-6 gap-y-1 text-sm">
              {ACTION_ORDER.map((action) => (
                <li key={action} data-testid={`count-${action}`} className="flex gap-2">
                  <span className="text-slate-400">{ACTION_LABEL[action]}</span>
                  <span className="tabular-nums text-slate-100">{queue.counts_by_action[action] ?? 0}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Panel>

      <Panel
        title="Orders"
        right={
          queue !== null && (
            <div className="flex items-center gap-3">
              <span data-testid="queue-range" className="text-xs tabular-nums text-slate-400">
                Showing {first}–{last} of {queue.total}
              </span>
              <button
                type="button"
                data-testid="page-previous"
                disabled={filters.offset === 0}
                onClick={() => update({ offset: Math.max(0, filters.offset - PAGE_SIZE) })}
                className="rounded border border-slate-700 px-2.5 py-1 text-xs text-slate-300 transition-colors duration-150 hover:bg-slate-800 disabled:opacity-40"
              >
                Previous
              </button>
              <button
                type="button"
                data-testid="page-next"
                disabled={last >= queue.total}
                onClick={() => update({ offset: filters.offset + PAGE_SIZE })}
                className="rounded border border-slate-700 px-2.5 py-1 text-xs text-slate-300 transition-colors duration-150 hover:bg-slate-800 disabled:opacity-40"
              >
                Next
              </button>
            </div>
          )
        }
      >
        {state.kind === 'loading' && <QueueSkeleton />}

        {state.kind === 'error' && (
          <div data-testid="queue-error">
            <p className="text-sm text-error">{state.message}</p>
            <button
              type="button"
              data-testid="queue-retry"
              onClick={load}
              className="mt-3 rounded border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 transition-colors duration-150 hover:bg-slate-700"
            >
              Retry
            </button>
          </div>
        )}

        {queue !== null && queue.items.length === 0 && (
          <div data-testid="queue-empty" className="py-6 text-center">
            <p className="text-sm text-slate-400">{EMPTY_MESSAGE}</p>
            <button
              type="button"
              data-testid="queue-empty-clear"
              onClick={clear}
              className="mt-2 text-sm text-slate-300 underline underline-offset-2"
            >
              Clear filters
            </button>
          </div>
        )}

        {queue !== null && queue.items.length > 0 && (
          <div className="overflow-x-auto">
            <table data-testid="queue-table" className="w-full min-w-0 text-left text-xs">
              <thead>
                <tr className="text-[11px] uppercase tracking-wide text-slate-500">
                  {COLUMNS.map((column) => (
                    <th
                      key={column}
                      scope="col"
                      className={`px-3 pb-2 font-medium ${
                        column.endsWith('probability') || column === 'Order value' ? 'text-right' : ''
                      }`}
                    >
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {queue.items.map((item) => (
                  <Row key={item.decision_id} item={item} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  )
}

export default QueuePage
