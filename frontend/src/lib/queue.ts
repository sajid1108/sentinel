/**
 * The queue's filter state, which lives in the URL query so a reload keeps it (§A).
 *
 * Every field here is a `QueueFilters` field from the generated contract, so the query string the page
 * builds is the query string the API takes: there is no second vocabulary to keep in step. Defaults are
 * omitted from the URL, which keeps a freshly opened queue at a clean `/queue`.
 */
import type { components } from '../api/types'

type QueueFilters = {
  action: components['schemas']['Action'] | null
  status: components['schemas']['QueueItem']['status'] | null
  source: components['schemas']['QueueItem']['source'] | null
  graph_evidence: 'ANY' | 'STRONG' | 'WEAK_ONLY' | 'NONE'
  sort: 'scored_at_desc' | 'p_abuse_desc' | 'value_desc' | 'exposure_desc'
  offset: number
}

export type QueueFilterState = QueueFilters

export const GRAPH_EVIDENCE_VALUES = ['ANY', 'STRONG', 'WEAK_ONLY', 'NONE'] as const
export const SORT_VALUES = ['scored_at_desc', 'p_abuse_desc', 'value_desc', 'exposure_desc'] as const
export const STATUS_VALUES = ['AUTO_APPLIED', 'PENDING_REVIEW', 'OVERRIDDEN', 'APPEAL_OPEN'] as const
export const SOURCE_VALUES = ['DEMO', 'BACKTEST_REPLAY', 'LIVE'] as const

/** Sentence-case labels for the enum values the filters expose. */
export const GRAPH_EVIDENCE_LABEL: Record<(typeof GRAPH_EVIDENCE_VALUES)[number], string> = {
  ANY: 'Any',
  STRONG: 'Strong',
  WEAK_ONLY: 'Weak only',
  NONE: 'None',
}

export const SORT_LABEL: Record<(typeof SORT_VALUES)[number], string> = {
  scored_at_desc: 'Newest first',
  p_abuse_desc: 'Abuse probability',
  value_desc: 'Order value',
  exposure_desc: 'Exposure',
}

export const STATUS_LABEL_QUEUE: Record<(typeof STATUS_VALUES)[number], string> = {
  AUTO_APPLIED: 'Auto applied',
  PENDING_REVIEW: 'Pending review',
  OVERRIDDEN: 'Overridden',
  APPEAL_OPEN: 'Appeal open',
}

export const SOURCE_LABEL: Record<(typeof SOURCE_VALUES)[number], string> = {
  DEMO: 'Demo',
  BACKTEST_REPLAY: 'Backtest replay',
  LIVE: 'Live',
}

/** The server's own default page size (`QueueFilters.limit`), sent explicitly so the URL is self-describing. */
export const PAGE_SIZE = 50

export const DEFAULT_FILTERS: QueueFilterState = {
  action: null,
  status: null,
  source: null,
  graph_evidence: 'ANY',
  sort: 'scored_at_desc',
  offset: 0,
}

function oneOf<T extends string>(values: readonly T[], raw: string | null): T | null {
  return raw !== null && (values as readonly string[]).includes(raw) ? (raw as T) : null
}

const ACTION_VALUES = ['ALLOW', 'PREPAID_ONLY', 'MANUAL_REVIEW', 'BLOCK'] as const

/** Read the filters out of a URL query. Anything unrecognised falls back to the default. */
export function filtersFromQuery(params: URLSearchParams): QueueFilterState {
  const offset = Number.parseInt(params.get('offset') ?? '', 10)
  return {
    action: oneOf(ACTION_VALUES, params.get('action')),
    status: oneOf(STATUS_VALUES, params.get('status')),
    source: oneOf(SOURCE_VALUES, params.get('source')),
    graph_evidence: oneOf(GRAPH_EVIDENCE_VALUES, params.get('graph_evidence')) ?? DEFAULT_FILTERS.graph_evidence,
    sort: oneOf(SORT_VALUES, params.get('sort')) ?? DEFAULT_FILTERS.sort,
    offset: Number.isFinite(offset) && offset > 0 ? offset : 0,
  }
}

/** The page's URL query: defaults are left out so an unfiltered queue reads `/queue`. */
export function queryFromFilters(filters: QueueFilterState): string {
  const params = new URLSearchParams()
  if (filters.action !== null) params.set('action', filters.action)
  if (filters.status !== null) params.set('status', filters.status)
  if (filters.source !== null) params.set('source', filters.source)
  if (filters.graph_evidence !== DEFAULT_FILTERS.graph_evidence) {
    params.set('graph_evidence', filters.graph_evidence)
  }
  if (filters.sort !== DEFAULT_FILTERS.sort) params.set('sort', filters.sort)
  if (filters.offset > 0) params.set('offset', String(filters.offset))
  return params.toString()
}

/** The API query, which always carries the page size and offset the request actually used. */
export function apiQueryFromFilters(filters: QueueFilterState): string {
  const params = new URLSearchParams(queryFromFilters(filters))
  params.set('limit', String(PAGE_SIZE))
  params.set('offset', String(filters.offset))
  if (!params.has('graph_evidence')) params.set('graph_evidence', filters.graph_evidence)
  if (!params.has('sort')) params.set('sort', filters.sort)
  return params.toString()
}

export function hasActiveFilters(filters: QueueFilterState): boolean {
  return (
    filters.action !== null ||
    filters.status !== null ||
    filters.source !== null ||
    filters.graph_evidence !== DEFAULT_FILTERS.graph_evidence
  )
}
