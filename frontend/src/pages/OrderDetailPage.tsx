/**
 * The order-detail screen: route `/orders/:orderId` (§12 phase 8, brief §B).
 *
 * Top to bottom: header and policy decision card, the two score cards, the expected-cost comparison, the
 * relationship graph beside the evidence panels, then the audit timeline and the baselines strip. Every
 * number is the server's: money is rendered from `Money.display`, probabilities are the only thing the
 * browser formats, and no threshold, cost or version is written into this file.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import type { components } from '../api/types'
import {
  ApiError,
  getOrderDetail,
  verifyAuditChain,
  type AuditVerifyResponse,
  type OrderDetailResponse,
  type PolicyAssumptionsResponse,
} from '../api/client'
import { AssumptionsPanel } from '../components/AssumptionsPanel'
import { AuditTimeline } from '../components/AuditTimeline'
import { BaselineComparison } from '../components/BaselineComparison'
import { CostComparison } from '../components/CostComparison'
import { AppealDialog, OverrideDialog } from '../components/OverrideDialog'
import { Field, Panel, Skeleton } from '../components/Panel'
import { PolicyDecisionCard } from '../components/PolicyDecisionCard'
import { EvidencePanel, ModelAttributionPanel } from '../components/ReasonList'
import { GraphLegend, RelationshipGraph } from '../components/RelationshipGraph'
import { ReviewerPicker, useReviewerId } from '../components/ReviewerPicker'
import { AbuseScoreCard, ReturnScoreCard } from '../components/ScorePair'
import { formatTimestamp } from '../lib/format'
import { blockConfidencePercent, usePolicyAssumptions } from '../lib/policy'

type DiscountReason = components['schemas']['DiscountedLink']['reason']

const DISCOUNT_LABEL: Record<DiscountReason, string> = {
  MULTI_TENANT_ADDRESS: 'multi-tenant address',
  SEQUENTIAL_DEVICE_USE: 'sequential device use',
  STALE_RELATIONSHIP: 'stale relationship',
  HIGH_FANOUT_IDENTIFIER: 'high-fanout identifier',
  HOUSEHOLD_PATTERN: 'household pattern',
}

export const NOT_FOUND_MESSAGE = 'Order not found'
export const EMPTY_GRAPH_MESSAGE = 'No relationships found for this order'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'ready'; detail: OrderDetailResponse }
  | { kind: 'missing' }
  | { kind: 'error'; message: string }

function DetailSkeleton() {
  return (
    <div data-testid="detail-skeleton" className="space-y-4">
      <Skeleton className="h-28 w-full" />
      <div className="grid grid-cols-2 gap-4">
        <Skeleton className="h-44 w-full" />
        <Skeleton className="h-44 w-full" />
      </div>
      <Skeleton className="h-72 w-full" />
      <div className="grid grid-cols-5 gap-4">
        <Skeleton className="col-span-3 h-96 w-full" />
        <Skeleton className="col-span-2 h-96 w-full" />
      </div>
    </div>
  )
}

export function OrderDetailPage() {
  const { orderId = '' } = useParams<{ orderId: string }>()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [verify, setVerify] = useState<AuditVerifyResponse | null>(null)
  const [assumptionsOpen, setAssumptionsOpen] = useState(false)
  const [overrideOpen, setOverrideOpen] = useState(false)
  const [appealOpen, setAppealOpen] = useState(false)
  const [reviewerId, setReviewerId] = useReviewerId()
  const policy = usePolicyAssumptions()

  /**
   * `silent` refetches without blanking the page. A dialog that has just recorded an override needs the
   * detail refreshed underneath it while it is still showing the server's warnings, so it must not be
   * unmounted by a skeleton.
   */
  const load = useCallback((silent = false) => {
    if (!silent) setState({ kind: 'loading' })
    getOrderDetail(orderId)
      .then((detail) => setState({ kind: 'ready', detail }))
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) setState({ kind: 'missing' })
        else setState({ kind: 'error', message: err instanceof ApiError ? err.detail : 'The order could not be loaded.' })
      })
  }, [orderId])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    let cancelled = false
    verifyAuditChain()
      .then((result) => {
        if (!cancelled) setVerify(result)
      })
      .catch(() => {
        if (!cancelled) setVerify(null)
      })
    return () => {
      cancelled = true
    }
  }, [orderId, state.kind])

  if (state.kind === 'loading') {
    return (
      <div className="p-6">
        <DetailSkeleton />
      </div>
    )
  }

  if (state.kind === 'missing') {
    return (
      <div className="p-6">
        <h1 className="text-xl font-semibold text-slate-100">{NOT_FOUND_MESSAGE}</h1>
        <Link to="/queue" className="mt-2 inline-block text-sm text-slate-400 underline underline-offset-2">
          Back to the queue
        </Link>
      </div>
    )
  }

  if (state.kind === 'error') {
    return (
      <div className="p-6">
        <h1 className="text-xl font-semibold text-slate-100">The order could not be loaded</h1>
        <p className="mt-1 text-sm text-slate-400">{state.message}</p>
        <button
          type="button"
          onClick={() => load()}
          className="mt-3 rounded border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 transition-colors duration-150 hover:bg-slate-700"
        >
          Retry
        </button>
      </div>
    )
  }

  return (
    <OrderDetail
      detail={state.detail}
      verify={verify}
      policy={policy}
      reviewerId={reviewerId}
      onReviewerChange={setReviewerId}
      assumptionsOpen={assumptionsOpen}
      setAssumptionsOpen={setAssumptionsOpen}
      overrideOpen={overrideOpen}
      setOverrideOpen={setOverrideOpen}
      appealOpen={appealOpen}
      setAppealOpen={setAppealOpen}
      reload={load}
    />
  )
}

function OrderDetail({
  detail,
  verify,
  policy,
  reviewerId,
  onReviewerChange,
  assumptionsOpen,
  setAssumptionsOpen,
  overrideOpen,
  setOverrideOpen,
  appealOpen,
  setAppealOpen,
  reload,
}: {
  detail: OrderDetailResponse
  verify: AuditVerifyResponse | null
  policy: PolicyAssumptionsResponse | null
  reviewerId: string
  onReviewerChange: (value: string) => void
  assumptionsOpen: boolean
  setAssumptionsOpen: (open: boolean) => void
  overrideOpen: boolean
  setOverrideOpen: (open: boolean) => void
  appealOpen: boolean
  setAppealOpen: (open: boolean) => void
  reload: (silent?: boolean) => void
}) {
  const { order, customer, decision, graph, baselines, audit_events: auditEvents } = detail
  const degraded = decision.degraded_mode
  const returnReasons = useMemo(() => decision.reasons.filter((r) => r.model === 'RETURN'), [decision.reasons])
  const summary = decision.graph_summary
  const linkedAccounts = graph.nodes.filter((n) => n.kind === 'ACCOUNT' && n.state !== 'CURRENT').length

  return (
    <div className="min-w-0 space-y-4 p-6">
      {/* B1 — header and policy decision card */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_minmax(0,26rem)]">
        <Panel>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-xl font-semibold text-slate-100">{order.order_id}</h1>
            <span
              data-testid="synthetic-badge"
              className="rounded border border-slate-600 bg-slate-800 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-300"
            >
              Synthetic
            </span>
            <ReviewerPicker value={reviewerId} onChange={onReviewerChange} />
          </div>
          <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
            <Field label="Placed">{formatTimestamp(order.placed_at)}</Field>
            <Field label="Order value">{order.order_value.display}</Field>
            <Field label="Account age">{customer.account_age_days} days</Field>
            <Field label="Prior orders">{customer.prior_orders}</Field>
            <Field label="Account">{customer.account_id}</Field>
            <Field label="Payment">{order.payment_method}</Field>
          </dl>
        </Panel>
        <PolicyDecisionCard
          decision={decision}
          currentAction={detail.current_action}
          onOverride={() => setOverrideOpen(true)}
          onAppeal={() => setAppealOpen(true)}
          busy={false}
        />
      </div>

      {/* B2 — two score cards, never merged */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ReturnScoreCard pReturn={decision.scores.p_return} reasons={returnReasons} />
        <AbuseScoreCard
          pAbuse={decision.scores.p_abuse}
          withoutGraph={decision.scores.p_abuse_without_graph_evidence}
          blockFromPercent={blockConfidencePercent(policy)}
        />
      </div>

      {/* B3 — expected-cost comparison */}
      <CostComparison
        policy={decision.policy}
        degraded={degraded}
        onOpenAssumptions={() => setAssumptionsOpen(true)}
      />

      {/* B4 + B5 — graph beside the evidence panels */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
        <div className="xl:col-span-3">
          <Panel
            title="Relationships"
            subtitle={
              <span data-testid="graph-counts">
                {graph.linked_orders_24h_shown} linked order
                {graph.linked_orders_24h_shown === 1 ? '' : 's'} in the last 24 h ·{' '}
                {graph.confirmed_peers_shown} confirmed account
                {graph.confirmed_peers_shown === 1 ? '' : 's'} on this device · component of{' '}
                {summary.component_size_reliable_90d}
                {graph.truncated && (
                  <>
                    {' · '}
                    <span data-testid="graph-truncated">
                      Showing {graph.nodes.length} of {graph.nodes.length + graph.hidden_node_count} nodes
                    </span>
                  </>
                )}
              </span>
            }
          >
            {linkedAccounts === 0 && (
              <p data-testid="graph-empty-notice" className="mb-3 text-sm text-slate-400">
                {EMPTY_GRAPH_MESSAGE}
              </p>
            )}
            <RelationshipGraph graph={graph} />
            <div className="mt-3">
              <GraphLegend />
            </div>
            {summary.signals.length > 0 && (
              <ul data-testid="signal-list" className="mt-3 space-y-1.5">
                {summary.signals.map((signal) => (
                  <li key={signal.signal} data-testid={`signal-${signal.signal}`} className="flex gap-2 text-xs">
                    <span
                      className={`w-32 shrink-0 ${signal.counts_for_corroboration ? 'text-slate-200' : 'text-slate-500'}`}
                    >
                      {signal.signal}
                    </span>
                    <span className="text-slate-400">{signal.detail}</span>
                  </li>
                ))}
              </ul>
            )}
            {summary.discounted_links.length > 0 && (
              <ul data-testid="discounted-links" className="mt-3 space-y-1 border-t border-slate-800 pt-3">
                {summary.discounted_links.map((link) => (
                  <li key={`${link.kind}-${link.identifier_label}`} className="text-xs text-slate-400">
                    {link.identifier_label} — discounted: {DISCOUNT_LABEL[link.reason]}
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
        <div className="space-y-4 xl:col-span-2">
          <EvidencePanel
            predictionExplanation={decision.prediction_explanation}
            reasons={decision.reasons}
          />
          <ModelAttributionPanel reasons={decision.reasons} />
        </div>
      </div>

      {/* B6 — audit timeline and baselines */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
        <div className="xl:col-span-3">
          <AuditTimeline events={auditEvents} verify={verify} />
        </div>
        <div className="xl:col-span-2">
          <BaselineComparison baselines={baselines} />
        </div>
      </div>

      <AssumptionsPanel policy={policy} open={assumptionsOpen} onClose={() => setAssumptionsOpen(false)} />
      {overrideOpen && (
        <OverrideDialog
          orderId={order.order_id}
          currentAction={detail.current_action}
          reviewerId={reviewerId}
          onClose={() => setOverrideOpen(false)}
          onApplied={() => reload(true)}
        />
      )}
      {appealOpen && (
        <AppealDialog
          orderId={order.order_id}
          reviewerId={reviewerId}
          onClose={() => setAppealOpen(false)}
          onOpened={() => reload(true)}
        />
      )}
    </div>
  )
}

export default OrderDetailPage
