/**
 * "Try an order" (Phase 10 §B, §D), against payloads recorded from the real backend: the builder options,
 * a checkout outcome and the decision page of the order that produced it.
 *
 * The failure modes these exist to catch: a request the server's contract would refuse, a token sent with
 * cash on delivery, the shopper's card leaking a score or an action, the two probabilities merged, a
 * double submission, the order scored twice, and a validation message that never reaches its field.
 */
import { cleanup, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import openapi from '../api/openapi.json'
import type { components } from '../api/types'
import checkoutFixture from '../__fixtures__/checkout-outcome.json'
import builderFixture from '../__fixtures__/order-builder.json'
import tryDetailFixture from '../__fixtures__/try-detail.json'
import {
  PLACING_LABEL,
  SHOPPER_CAPTION,
  TEAM_CAPTION,
  UNKNOWN_ACCOUNT_MESSAGE,
} from '../components/TryAnOrder'
import { ACTION_LABEL, ACTION_ORDER } from '../lib/actions'
import { formatProbability } from '../lib/format'
import {
  BOUNDS,
  SIZES,
  buildRequest,
  initialForm,
  newOrderId,
  validate,
  type OrderBuilderResponse,
  type TryForm,
} from '../lib/tryOrder'
import { renderApp, stubApi } from './render'

type CheckoutOutcome = components['schemas']['CheckoutOutcome']
type OrderDetailResponse = components['schemas']['OrderDetailResponse']

const BUILDER = builderFixture as unknown as OrderBuilderResponse
const OUTCOME = checkoutFixture as unknown as CheckoutOutcome
const DETAIL = tryDetailFixture as unknown as OrderDetailResponse
const CHECKOUT_PATH = '/api/v1/public/checkout/decision'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

type Handler = (url: string, init?: RequestInit) => { status: number; body: unknown } | null

async function openTry(extra: Handler | null = null) {
  const api = stubApi((url, init) => {
    const handled = extra?.(url, init)
    if (handled) return handled
    if (url.includes('/demo/order-builder')) return { status: 200, body: BUILDER }
    if (url.endsWith(CHECKOUT_PATH)) return { status: 200, body: OUTCOME }
    if (url.includes(`/internal/orders/${OUTCOME.order_id}`)) return { status: 200, body: DETAIL }
    return null
  })
  renderApp('/queue')
  await screen.findByTestId('try-form')
  return api
}

function fill(values: Partial<Record<string, string>>) {
  for (const [id, value] of Object.entries(values)) {
    fireEvent.change(screen.getByLabelText(labelFor(id)), { target: { value } })
  }
}

const LABELS: Record<string, string> = {
  price: 'Item price (₹)',
  quantity: 'Quantity',
  sizes: 'Sizes of the same item',
  discount: 'Discount (%)',
  payment: 'Payment method',
  device: 'Device',
  token: 'Payment token',
  account: 'Account',
  category: 'Category',
}
const labelFor = (id: string) => LABELS[id]

function withOwnIdentifiers(): string {
  const account = BUILDER.accounts.find((a) => a.device_id && a.payment_token_id)
  if (!account) throw new Error('the recorded builder has no account with its own device and token')
  return account.account_id
}

function form(overrides: Partial<TryForm> = {}): TryForm {
  return { ...initialForm(BUILDER), accountId: withOwnIdentifiers(), price: '1499', ...overrides }
}

// ── a minimal JSON-schema check against the generated OpenAPI document ────────
type Schema = {
  $ref?: string
  type?: string
  enum?: unknown[]
  pattern?: string
  minimum?: number
  maximum?: number
  exclusiveMinimum?: number
  minItems?: number
  maxItems?: number
  items?: Schema
  properties?: Record<string, Schema>
  required?: string[]
  additionalProperties?: boolean
  anyOf?: Schema[]
  format?: string
}
const SCHEMAS = openapi.components.schemas as unknown as Record<string, Schema>

function violations(value: unknown, schema: Schema, path = '$'): string[] {
  if (schema.$ref) return violations(value, SCHEMAS[schema.$ref.split('/').pop() as string], path)
  if (schema.anyOf) {
    return schema.anyOf.some((s) => violations(value, s, path).length === 0) ? [] : [`${path}: no anyOf branch`]
  }
  const out: string[] = []
  if (schema.type === 'null') return value === null ? [] : [`${path}: not null`]
  if (schema.enum && !schema.enum.includes(value)) out.push(`${path}: not in enum`)
  if (schema.type === 'string') {
    if (typeof value !== 'string') return [`${path}: not a string`]
    if (schema.pattern && !new RegExp(schema.pattern).test(value)) out.push(`${path}: pattern`)
    if (schema.format === 'date-time' && Number.isNaN(Date.parse(value))) out.push(`${path}: date-time`)
  }
  if (schema.type === 'number' || schema.type === 'integer') {
    if (typeof value !== 'number') return [`${path}: not a number`]
    if (schema.type === 'integer' && !Number.isInteger(value)) out.push(`${path}: not an integer`)
    if (schema.minimum !== undefined && value < schema.minimum) out.push(`${path}: below minimum`)
    if (schema.maximum !== undefined && value > schema.maximum) out.push(`${path}: above maximum`)
    if (schema.exclusiveMinimum !== undefined && value <= schema.exclusiveMinimum) out.push(`${path}: not above`)
  }
  if (schema.type === 'array') {
    if (!Array.isArray(value)) return [`${path}: not an array`]
    if (schema.minItems !== undefined && value.length < schema.minItems) out.push(`${path}: too few`)
    if (schema.maxItems !== undefined && value.length > schema.maxItems) out.push(`${path}: too many`)
    value.forEach((v, i) => out.push(...violations(v, schema.items ?? {}, `${path}[${i}]`)))
  }
  if (schema.type === 'object' || schema.properties) {
    if (typeof value !== 'object' || value === null) return [`${path}: not an object`]
    const record = value as Record<string, unknown>
    for (const key of schema.required ?? []) if (!(key in record)) out.push(`${path}.${key}: missing`)
    for (const [key, v] of Object.entries(record)) {
      const sub = schema.properties?.[key]
      if (!sub) {
        if (schema.additionalProperties === false) out.push(`${path}.${key}: not allowed`)
        continue
      }
      out.push(...violations(v, sub, `${path}.${key}`))
    }
  }
  return out
}

// ── the request ──────────────────────────────────────────────────────────────
describe('the form builds a request the server contract accepts', () => {
  it('validates against the generated ScoreOrderRequest schema for every payment method and choice', () => {
    for (const payment of ['PREPAID_UPI', 'PREPAID_CARD', 'COD'] as const) {
      for (const device of BUILDER.devices.map((d) => d.option)) {
        for (const token of BUILDER.tokens.map((t) => t.option)) {
          const f = form({ payment, device, token, sizes: String(SIZES.length), discount: '15' })
          expect(validate(f, BUILDER)).toEqual({})
          const request = buildRequest(f, BUILDER, newOrderId())
          expect(violations(request, SCHEMAS.ScoreOrderRequest)).toEqual([])
        }
      }
    }
  })

  it('makes one line per size of one product, with ids from the category', () => {
    const request = buildRequest(form({ sizes: '3', category: 'FOOTWEAR' }), BUILDER, 'ORD-TRY-0A1B2C3D')
    expect(request.lines).toHaveLength(3)
    expect(new Set(request.lines.map((l) => l.product_id))).toEqual(new Set(['PRD-TRY-FOOTWEAR']))
    expect(request.lines.map((l) => l.sku_id)).toEqual([1, 2, 3].map((n) => `SKU-TRY-FOOTWEAR-${n}`))
    expect(new Set(request.lines.map((l) => l.variant)).size).toBe(3)
    expect(request.placed_at).toBe(BUILDER.placed_at)
  })

  it('uses the builder identifiers, never a typed one', () => {
    const account = BUILDER.accounts.find((a) => a.account_id === withOwnIdentifiers())
    const own = buildRequest(form(), BUILDER, 'ORD-TRY-00000000')
    expect([own.device_id, own.address_id, own.payment_token_id]).toEqual([
      account?.device_id,
      account?.address_id,
      account?.payment_token_id,
    ])
    const ring = buildRequest(form({ device: 'RING', token: 'RING' }), BUILDER, 'ORD-TRY-00000000')
    expect(ring.device_id).toBe(BUILDER.devices.find((d) => d.option === 'RING')?.identifier_id)
    expect(ring.payment_token_id).toBe(BUILDER.tokens.find((t) => t.option === 'RING')?.identifier_id)
  })

  it('makes order ids ORD-TRY- plus 8 upper-case hex characters', () => {
    for (let i = 0; i < 50; i += 1) expect(newOrderId()).toMatch(/^ORD-TRY-[0-9A-F]{8}$/)
  })

  it('nulls the token for cash on delivery and hides the token field', async () => {
    const request = buildRequest(form({ payment: 'COD', token: 'RING' }), BUILDER, 'ORD-TRY-00000000')
    expect(request.payment_token_id).toBeNull()
    await openTry()
    expect(screen.getByLabelText(labelFor('token'))).toBeInTheDocument()
    fill({ payment: 'COD' })
    expect(screen.queryByLabelText(labelFor('token'))).toBeNull()
  })

  it('reads its bounds from the OpenAPI contract', () => {
    const line = openapi.components.schemas.OrderLineIn.properties
    expect(BOUNDS.price.maximum).toBe(line.unit_price_inr.maximum)
    expect(BOUNDS.quantity.maximum).toBe(line.quantity.maximum)
    expect(BOUNDS.discount.maximum).toBe(openapi.components.schemas.ScoreOrderRequest.properties.discount_pct.maximum)
    const tooMuch = String((BOUNDS.price.maximum ?? 0) + 1)
    expect(validate(form({ price: tooMuch }), BUILDER).price).toMatch(/at most/)
  })
})

// ── submitting ───────────────────────────────────────────────────────────────
describe('placing an order', () => {
  it('sends the order once to the public checkout, then reads the decision, never scoring twice', async () => {
    const { calls } = await openTry()
    fill({ account: withOwnIdentifiers(), price: '1499' })
    fireEvent.click(screen.getByTestId('try-submit'))
    await screen.findByTestId('try-result')
    const checkouts = calls.filter((c) => c.url.endsWith(CHECKOUT_PATH))
    expect(checkouts).toHaveLength(1)
    expect(checkouts[0].init?.method).toBe('POST')
    const sent = JSON.parse(String(checkouts[0].init?.body))
    expect(violations(sent, SCHEMAS.ScoreOrderRequest)).toEqual([])
    expect(calls.some((c) => c.url.includes('/score-order') || c.url.endsWith('/score'))).toBe(false)
    expect(calls.some((c) => c.url.includes(`/internal/orders/${OUTCOME.order_id}`))).toBe(true)
  })

  it('reads "Placing order…" and disables the button while the request runs', async () => {
    let release: () => void = () => undefined
    const pending = new Promise<void>((resolve) => {
      release = resolve
    })
    const api = await openTry()
    const base = api.fetchStub.getMockImplementation()
    api.fetchStub.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith(CHECKOUT_PATH)) await pending
      return base!(input, init)
    })
    fill({ account: withOwnIdentifiers(), price: '1499' })
    fireEvent.click(screen.getByTestId('try-submit'))
    const button = await screen.findByRole('button', { name: PLACING_LABEL })
    expect(button).toBeDisabled()
    fireEvent.click(button)
    release()
    await screen.findByTestId('try-result')
    expect(api.calls.filter((c) => c.url.endsWith(CHECKOUT_PATH))).toHaveLength(1)
    expect(screen.getByTestId('try-submit')).not.toBeDisabled()
  })

  it('shows field messages beside their fields and sends nothing', async () => {
    const { calls } = await openTry()
    fill({ price: '', quantity: '0', discount: String((BOUNDS.discount.maximum ?? 0) + 1) })
    fireEvent.click(screen.getByTestId('try-submit'))
    for (const id of ['price', 'quantity', 'discount']) {
      const input = screen.getByLabelText(labelFor(id))
      const message = await screen.findByTestId(`try-${id}-error`)
      expect(input.getAttribute('aria-describedby')).toBe(message.id)
    }
    expect(calls.some((c) => c.url.endsWith(CHECKOUT_PATH))).toBe(false)
  })

  it("shows the server's 422 message when the server still refuses", async () => {
    await openTry((url) =>
      url.endsWith(CHECKOUT_PATH) ? { status: 422, body: { detail: 'The request could not be processed.' } } : null,
    )
    fill({ account: withOwnIdentifiers(), price: '1499' })
    fireEvent.click(screen.getByTestId('try-submit'))
    expect(await screen.findByTestId('try-rejected')).toHaveTextContent('The request could not be processed.')
  })

  it('names an unknown account on a 404', async () => {
    await openTry((url) => (url.endsWith(CHECKOUT_PATH) ? { status: 404, body: { detail: 'Not found.' } } : null))
    fill({ account: withOwnIdentifiers(), price: '1499' })
    fireEvent.click(screen.getByTestId('try-submit'))
    expect(await screen.findByTestId('try-rejected')).toHaveTextContent(UNKNOWN_ACCOUNT_MESSAGE)
  })

  it('offers Retry on other errors, and a retry resends the same order', async () => {
    let fail = true
    const { calls } = await openTry((url) =>
      url.endsWith(CHECKOUT_PATH) && fail ? { status: 500, body: { detail: 'Internal Server Error' } } : null,
    )
    fill({ account: withOwnIdentifiers(), price: '1499' })
    fireEvent.click(screen.getByTestId('try-submit'))
    await screen.findByTestId('try-failed')
    fail = false
    fireEvent.click(screen.getByTestId('try-retry'))
    await screen.findByTestId('try-result')
    const bodies = calls.filter((c) => c.url.endsWith(CHECKOUT_PATH)).map((c) => c.init?.body)
    expect(bodies).toHaveLength(2)
    expect(bodies[0]).toBe(bodies[1])
  })

  it('renders nothing when the builder route 404s (DEMO_MODE off)', async () => {
    stubApi()
    renderApp('/queue')
    await screen.findByTestId('queue-table')
    expect(screen.queryByTestId('try-form')).toBeNull()
  })
})

// ── the two views ────────────────────────────────────────────────────────────
describe('the result shows the shopper and the team different things', () => {
  async function placed() {
    await openTry()
    fill({ account: withOwnIdentifiers(), price: '1499' })
    fireEvent.click(screen.getByTestId('try-submit'))
    await screen.findByTestId('try-result')
  }

  it('gives the shopper only the outcome strings: no %, no action name, no colour', async () => {
    await placed()
    expect(screen.getByText(SHOPPER_CAPTION)).toBeInTheDocument()
    const card = screen.getByTestId('shopper-card')
    const allowed = new Set([OUTCOME.customer_message, OUTCOME.support_reference])
    const texts = Array.from(card.querySelectorAll('*'))
      .filter((el) => el.children.length === 0)
      .map((el) => el.textContent ?? '')
      .filter((t) => t.trim() !== '')
    expect(texts.length).toBeGreaterThan(0)
    expect(texts.every((t) => allowed.has(t))).toBe(true)
    const text = card.textContent ?? ''
    expect(text).not.toMatch(/%/)
    for (const action of ACTION_ORDER) {
      expect(text).not.toContain(action)
      expect(text.toLowerCase()).not.toContain(ACTION_LABEL[action].toLowerCase())
    }
    expect(card.innerHTML).not.toMatch(/(allow|prepaid|review|block|return)\b/i)
    expect(card.querySelector('[data-action]')).toBeNull()
  })

  it('gives the team the badge, two separate probabilities, the explanation and a link', async () => {
    await placed()
    expect(screen.getByText(TEAM_CAPTION)).toBeInTheDocument()
    const card = within(screen.getByTestId('team-card'))
    expect(screen.getByTestId('team-card').querySelector(`[data-action="${DETAIL.current_action}"]`)).not.toBeNull()
    const pReturn = card.getByTestId('team-p-return')
    const pAbuse = card.getByTestId('team-p-abuse')
    expect(pReturn).not.toBe(pAbuse)
    expect(pReturn.contains(pAbuse) || pAbuse.contains(pReturn)).toBe(false)
    expect(pReturn).toHaveTextContent(formatProbability(DETAIL.decision.scores.p_return))
    expect(pAbuse).toHaveTextContent(formatProbability(DETAIL.decision.scores.p_abuse))
    expect(card.getByTestId('team-explanation').textContent).toBe(DETAIL.decision.policy.policy_explanation)
    expect(card.getByTestId('team-order-value').textContent).toBe(DETAIL.order.order_value.display)
    expect(card.getByRole('link', { name: 'Open full decision' })).toHaveAttribute(
      'href',
      `/orders/${OUTCOME.order_id}`,
    )
  })

  it('never formats money from the typed price', async () => {
    await placed()
    const panel = screen.getByTestId('try-result')
    expect(panel.textContent).not.toContain('1,499')
    expect(panel.textContent).not.toContain('1499')
  })
})
