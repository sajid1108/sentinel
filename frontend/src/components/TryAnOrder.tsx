/**
 * "Try an order" (Phase 10 §B), beside Simulate checkout on the Queue page.
 *
 * The form builds one `ScoreOrderRequest` from `GET /internal/demo/order-builder` and sends it once to the
 * public checkout, which scores it (source LIVE) and answers with the customer outcome. The reviewer view
 * is then read from `GET /internal/orders/{id}`: the checkout already wrote the decision, so nothing is
 * scored twice. The panel exists only when the builder route answers, i.e. only when DEMO_MODE is on.
 *
 * The shopper's card shows the outcome's message and support reference verbatim and nothing else: no score,
 * action, reason, cost or colour. Money is never formatted from what was typed: the order value shown is the
 * server's `order_value.display`.
 */
import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import {
  ApiError,
  getOrderBuilder,
  getOrderDetail,
  postCheckout,
  type CheckoutOutcome,
  type OrderBuilderResponse,
  type OrderDetailResponse,
  type ScoreOrderRequest,
} from '../api/client'
import { formatProbability } from '../lib/format'
import {
  BOUNDS,
  DELIVERY_LABEL,
  DELIVERY_OPTIONS,
  PAYMENT_LABEL,
  PAYMENT_OPTIONS,
  SIZE_BOUNDS,
  buildRequest,
  initialForm,
  isCod,
  newOrderId,
  validate,
  type Field,
  type FieldErrors,
  type TryForm,
} from '../lib/tryOrder'
import { ActionBadge } from './ActionBadge'
import { Panel } from './Panel'

export const PLACING_LABEL = 'Placing order…'
export const PLACE_LABEL = 'Place order'
export const UNKNOWN_ACCOUNT_MESSAGE = "This account doesn't exist in the demo world."
export const SHOPPER_CAPTION = 'What the shopper sees.'
export const TEAM_CAPTION = 'What your team sees.'
const FAILED_MESSAGE = 'The order could not be placed.'

type Result = { outcome: CheckoutOutcome; detail: OrderDetailResponse }

type Submit =
  | { kind: 'idle' }
  | { kind: 'placing' }
  | { kind: 'rejected'; message: string }
  | { kind: 'failed'; message: string; request: ScoreOrderRequest; outcome: CheckoutOutcome | null }
  | { kind: 'done'; result: Result }

const INPUT =
  'rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100 focus:border-sky-300 focus:outline-none'

function Control({
  id,
  label,
  error,
  className = '',
  children,
}: {
  id: string
  label: string
  error?: string
  className?: string
  children: ReactNode
}) {
  return (
    <div className={`flex min-w-0 flex-col gap-1 ${className}`}>
      <label htmlFor={id} className="text-xs text-slate-400">
        {label}
      </label>
      {children}
      {error && (
        <span id={`${id}-error`} data-testid={`${id}-error`} className="text-xs text-error">
          {error}
        </span>
      )}
    </div>
  )
}

function ShopperCard({ outcome }: { outcome: CheckoutOutcome }) {
  return (
    <figure className="min-w-0">
      <figcaption className="mb-1.5 text-xs text-slate-400">{SHOPPER_CAPTION}</figcaption>
      <div data-testid="shopper-card" className="rounded border border-slate-700 bg-slate-950 p-4">
        <p className="text-sm text-slate-100">{outcome.customer_message}</p>
        <p className="mt-2 font-mono text-xs text-slate-400">{outcome.support_reference}</p>
      </div>
    </figure>
  )
}

function TeamCard({ orderId, detail }: { orderId: string; detail: OrderDetailResponse }) {
  const { scores, policy } = detail.decision
  return (
    <figure className="min-w-0">
      <figcaption className="mb-1.5 text-xs text-slate-400">{TEAM_CAPTION}</figcaption>
      <div data-testid="team-card" className="space-y-3 rounded border border-slate-700 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <ActionBadge action={detail.current_action} />
          <span data-testid="team-order-value" className="text-sm text-slate-300">
            {detail.order.order_value.display}
          </span>
        </div>
        <dl className="grid grid-cols-2 gap-3">
          <div data-testid="team-p-return">
            <dt className="text-xs text-slate-400">Return probability</dt>
            <dd className="text-lg font-semibold text-return">{formatProbability(scores.p_return)}</dd>
          </div>
          <div data-testid="team-p-abuse">
            <dt className="text-xs text-slate-400">Abuse probability</dt>
            <dd className="text-lg font-semibold text-slate-100">{formatProbability(scores.p_abuse)}</dd>
          </div>
        </dl>
        <p data-testid="team-explanation" className="text-sm text-slate-300">
          {policy.policy_explanation}
        </p>
        <Link
          to={`/orders/${encodeURIComponent(orderId)}`}
          className="inline-block text-sm text-sky-300 underline-offset-2 hover:underline"
        >
          Open full decision
        </Link>
      </div>
    </figure>
  )
}

export function TryAnOrder({ onPlaced }: { onPlaced: () => void }) {
  const [builder, setBuilder] = useState<OrderBuilderResponse | null>(null)
  const [form, setForm] = useState<TryForm | null>(null)
  const [errors, setErrors] = useState<FieldErrors>({})
  const [submit, setSubmit] = useState<Submit>({ kind: 'idle' })

  useEffect(() => {
    let cancelled = false
    getOrderBuilder()
      .then((body) => {
        if (cancelled) return
        setBuilder(body)
        setForm(initialForm(body))
      })
      .catch(() => {
        // 404 means DEMO_MODE is off: there is no panel to show.
        if (!cancelled) setBuilder(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (builder === null || form === null) return null

  const set = <K extends keyof TryForm>(key: K, value: TryForm[K]) => {
    setForm({ ...form, [key]: value })
    if (key in errors) {
      const { [key as Field]: _removed, ...rest } = errors
      setErrors(rest)
    }
  }

  const send = (request: ScoreOrderRequest, known: CheckoutOutcome | null) => {
    setSubmit({ kind: 'placing' })
    // Retrying after the checkout answered only re-reads the decision; the order is never sent twice.
    const checkout = known ? Promise.resolve(known) : postCheckout(request)
    checkout
      .then((outcome) =>
        getOrderDetail(outcome.order_id)
          .then((detail) => {
            setSubmit({ kind: 'done', result: { outcome, detail } })
            onPlaced()
          })
          .catch((err: unknown) => {
            onPlaced()
            setSubmit({ kind: 'failed', message: messageOf(err), request, outcome })
          }),
      )
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) {
          setSubmit({ kind: 'rejected', message: UNKNOWN_ACCOUNT_MESSAGE })
        } else if (err instanceof ApiError && err.status === 422) {
          setSubmit({ kind: 'rejected', message: err.detail })
        } else {
          setSubmit({ kind: 'failed', message: messageOf(err), request, outcome: null })
        }
      })
  }

  const place = () => {
    const found = validate(form, builder)
    setErrors(found)
    if (Object.keys(found).length > 0) {
      setSubmit({ kind: 'idle' })
      return
    }
    send(buildRequest(form, builder, newOrderId()), null)
  }

  const account = builder.accounts.find((a) => a.account_id === form.accountId)
  const placing = submit.kind === 'placing'
  const describedBy = (id: Field) => (errors[id] ? `try-${id}-error` : undefined)

  return (
    <Panel
      title="Try an order"
      subtitle="Build an order and place it through the real checkout: see what the shopper is told and what your team sees."
    >
      <form
        data-testid="try-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault()
          place()
        }}
        className="grid grid-cols-2 gap-3 sm:grid-cols-4"
      >
        <Control id="try-accountId" label="Account" error={errors.accountId} className="col-span-2 sm:col-span-4">
          <select
            id="try-accountId"
            value={form.accountId}
            aria-describedby={describedBy('accountId')}
            onChange={(e) => set('accountId', e.target.value)}
            className={INPUT}
          >
            {builder.accounts.map((a) => (
              <option key={a.account_id} value={a.account_id}>
                {a.account_id} · {a.label} · {a.prior_orders} prior orders · {a.account_age_days} days old
              </option>
            ))}
          </select>
        </Control>
        <Control id="try-category" label="Category" error={errors.category}>
          <select
            id="try-category"
            value={form.category}
            aria-describedby={describedBy('category')}
            onChange={(e) => set('category', e.target.value as TryForm['category'])}
            className={INPUT}
          >
            {builder.categories.map((c) => (
              <option key={c} value={c}>
                {c.charAt(0) + c.slice(1).toLowerCase()}
              </option>
            ))}
          </select>
        </Control>
        <Control id="try-price" label="Item price (₹)" error={errors.price}>
          <input
            id="try-price"
            type="number"
            inputMode="decimal"
            max={BOUNDS.price.maximum}
            value={form.price}
            aria-invalid={errors.price ? true : undefined}
            aria-describedby={describedBy('price')}
            onChange={(e) => set('price', e.target.value)}
            className={INPUT}
          />
        </Control>
        <Control id="try-quantity" label="Quantity" error={errors.quantity}>
          <input
            id="try-quantity"
            type="number"
            min={BOUNDS.quantity.minimum}
            max={BOUNDS.quantity.maximum}
            value={form.quantity}
            aria-invalid={errors.quantity ? true : undefined}
            aria-describedby={describedBy('quantity')}
            onChange={(e) => set('quantity', e.target.value)}
            className={INPUT}
          />
        </Control>
        <Control id="try-sizes" label="Sizes of the same item" error={errors.sizes}>
          <input
            id="try-sizes"
            type="number"
            min={SIZE_BOUNDS.minimum}
            max={SIZE_BOUNDS.maximum}
            value={form.sizes}
            aria-invalid={errors.sizes ? true : undefined}
            aria-describedby={describedBy('sizes')}
            onChange={(e) => set('sizes', e.target.value)}
            className={INPUT}
          />
        </Control>
        <Control id="try-discount" label="Discount (%)" error={errors.discount}>
          <input
            id="try-discount"
            type="number"
            min={BOUNDS.discount.minimum}
            max={BOUNDS.discount.maximum}
            value={form.discount}
            aria-invalid={errors.discount ? true : undefined}
            aria-describedby={describedBy('discount')}
            onChange={(e) => set('discount', e.target.value)}
            className={INPUT}
          />
        </Control>
        <Control id="try-delivery" label="Delivery speed">
          <select
            id="try-delivery"
            value={form.delivery}
            onChange={(e) => set('delivery', e.target.value as TryForm['delivery'])}
            className={INPUT}
          >
            {DELIVERY_OPTIONS.map((d) => (
              <option key={d} value={d}>
                {DELIVERY_LABEL[d]}
              </option>
            ))}
          </select>
        </Control>
        <Control id="try-payment" label="Payment method">
          <select
            id="try-payment"
            value={form.payment}
            onChange={(e) => set('payment', e.target.value as TryForm['payment'])}
            className={INPUT}
          >
            {PAYMENT_OPTIONS.map((p) => (
              <option key={p} value={p}>
                {PAYMENT_LABEL[p]}
              </option>
            ))}
          </select>
        </Control>
        <Control id="try-device" label="Device" error={errors.device} className="col-span-2">
          <select
            id="try-device"
            value={form.device}
            aria-describedby={describedBy('device')}
            onChange={(e) => set('device', e.target.value as TryForm['device'])}
            className={INPUT}
          >
            {builder.devices.map((d) => (
              <option key={d.option} value={d.option} disabled={d.option === 'OWN' && !account?.device_id}>
                {d.label}
              </option>
            ))}
          </select>
        </Control>
        {!isCod(form.payment) && (
          <Control id="try-token" label="Payment token" error={errors.token} className="col-span-2">
            <select
              id="try-token"
              value={form.token}
              aria-describedby={describedBy('token')}
              onChange={(e) => set('token', e.target.value as TryForm['token'])}
              className={INPUT}
            >
              {builder.tokens.map((t) => (
                <option
                  key={t.option}
                  value={t.option}
                  disabled={t.option === 'OWN' && !account?.payment_token_id}
                >
                  {t.label}
                </option>
              ))}
            </select>
          </Control>
        )}
        <div className="col-span-2 flex flex-wrap items-center gap-3 sm:col-span-4">
          <button
            type="submit"
            data-testid="try-submit"
            disabled={placing}
            className="rounded border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 transition-colors duration-150 hover:bg-slate-700 disabled:opacity-50"
          >
            {placing ? PLACING_LABEL : PLACE_LABEL}
          </button>
          {submit.kind === 'rejected' && (
            <span role="alert" data-testid="try-rejected" className="text-sm text-error">
              {submit.message}
            </span>
          )}
          {submit.kind === 'failed' && (
            <span role="alert" className="flex flex-wrap items-center gap-3">
              <span data-testid="try-failed" className="text-sm text-error">
                {submit.message}
              </span>
              <button
                type="button"
                data-testid="try-retry"
                onClick={() => send(submit.request, submit.outcome)}
                className="rounded border border-slate-700 px-3 py-1.5 text-sm text-slate-300 transition-colors duration-150 hover:bg-slate-800"
              >
                Retry
              </button>
            </span>
          )}
        </div>
      </form>

      {submit.kind === 'done' && (
        <div data-testid="try-result" className="mt-4 grid gap-4 border-t border-slate-800 pt-4 md:grid-cols-2">
          <ShopperCard outcome={submit.result.outcome} />
          <TeamCard orderId={submit.result.outcome.order_id} detail={submit.result.detail} />
        </div>
      )}
    </Panel>
  )
}

function messageOf(err: unknown): string {
  return err instanceof ApiError ? `${FAILED_MESSAGE} (${err.status})` : FAILED_MESSAGE
}
