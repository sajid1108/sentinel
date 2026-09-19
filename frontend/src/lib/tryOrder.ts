/**
 * "Try an order" (Phase 10 §B): the form's state, its checks and the request it builds.
 *
 * Nothing here is a policy value and nothing is typed free-hand. Accounts, identifiers, categories and
 * `placed_at` come from `GET /internal/demo/order-builder`; every numeric bound comes from the generated
 * OpenAPI document, which is the server's own `ScoreOrderRequest` contract. The public checkout route answers
 * a 422 with one fixed sentence and no field locations (#34), so the field messages are these checks, run
 * before anything is sent; the server stays the judge and its sentence is shown if it still refuses.
 */
import openapi from '../api/openapi.json'
import type { components } from '../api/types'

import type { OrderBuilderResponse, ScoreOrderRequest } from '../api/client'

export type { OrderBuilderResponse, ScoreOrderRequest }
export type BuilderIdentifierOption = components['schemas']['BuilderIdentifierOption']
export type Category = ScoreOrderRequest['lines'][number]['category']
export type PaymentMethod = ScoreOrderRequest['payment_method']
export type DeliverySpeed = ScoreOrderRequest['delivery_speed']
export type IdentifierChoice = BuilderIdentifierOption['option']

type NumberSchema = { minimum?: number; maximum?: number; exclusiveMinimum?: number }

const SCHEMAS = openapi.components.schemas
const LINE = SCHEMAS.OrderLineIn.properties
const ORDER = SCHEMAS.ScoreOrderRequest.properties

export const BOUNDS = {
  price: LINE.unit_price_inr as NumberSchema,
  quantity: LINE.quantity as NumberSchema,
  discount: ORDER.discount_pct as NumberSchema,
}

/** Size bracketing: one line per size of the same product. The count is bounded by this list. */
export const SIZES = ['S', 'M', 'L', 'XL'] as const

export const DELIVERY_LABEL: Record<DeliverySpeed, string> = { STANDARD: 'Standard', EXPRESS: 'Express' }
export const PAYMENT_LABEL: Record<PaymentMethod, string> = {
  PREPAID_UPI: 'UPI',
  PREPAID_CARD: 'Card',
  COD: 'Cash on delivery',
}
export const DELIVERY_OPTIONS = ORDER.delivery_speed.enum as DeliverySpeed[]
export const PAYMENT_OPTIONS = ORDER.payment_method.enum as PaymentMethod[]

export type TryForm = {
  accountId: string
  category: Category | ''
  price: string
  quantity: string
  sizes: string
  discount: string
  delivery: DeliverySpeed
  payment: PaymentMethod
  device: IdentifierChoice
  token: IdentifierChoice
}

export type Field = 'accountId' | 'category' | 'price' | 'quantity' | 'sizes' | 'discount' | 'device' | 'token'
export type FieldErrors = Partial<Record<Field, string>>

export function initialForm(builder: OrderBuilderResponse): TryForm {
  return {
    accountId: builder.accounts[0]?.account_id ?? '',
    category: builder.categories[0] ?? '',
    price: '',
    quantity: '1',
    sizes: '1',
    discount: '0',
    delivery: DELIVERY_OPTIONS[0],
    payment: PAYMENT_OPTIONS[0],
    device: 'OWN',
    token: 'OWN',
  }
}

export const isCod = (payment: PaymentMethod) => payment === 'COD'

function rangeMessage(bounds: NumberSchema): string {
  const low =
    bounds.exclusiveMinimum !== undefined ? `greater than ${bounds.exclusiveMinimum}` : `at least ${bounds.minimum}`
  return bounds.maximum === undefined ? `Must be ${low}.` : `Must be ${low} and at most ${bounds.maximum}.`
}

function checkNumber(text: string, bounds: NumberSchema, integer: boolean): string | null {
  if (text.trim() === '') return 'Required.'
  const value = Number(text)
  if (!Number.isFinite(value)) return 'Enter a number.'
  if (integer && !Number.isInteger(value)) return 'Enter a whole number.'
  const low =
    bounds.exclusiveMinimum !== undefined ? value > bounds.exclusiveMinimum : value >= (bounds.minimum ?? -Infinity)
  const high = value <= (bounds.maximum ?? Infinity)
  return low && high ? null : rangeMessage(bounds)
}

export const SIZE_BOUNDS: NumberSchema = { minimum: 1, maximum: SIZES.length }

/** The identifier a choice stands for, or null when this account has none of its own. */
export function resolveIdentifier(
  choice: IdentifierChoice,
  options: BuilderIdentifierOption[],
  own: string | null,
): string | null {
  if (choice === 'OWN') return own
  return options.find((o) => o.option === choice)?.identifier_id ?? null
}

export function validate(form: TryForm, builder: OrderBuilderResponse): FieldErrors {
  const errors: FieldErrors = {}
  const account = builder.accounts.find((a) => a.account_id === form.accountId)
  if (!account) errors.accountId = 'Choose an account.'
  if (form.category === '') errors.category = 'Choose a category.'
  const checks: [Field, string, NumberSchema, boolean][] = [
    ['price', form.price, BOUNDS.price, false],
    ['quantity', form.quantity, BOUNDS.quantity, true],
    ['sizes', form.sizes, SIZE_BOUNDS, true],
    ['discount', form.discount, BOUNDS.discount, false],
  ]
  for (const [field, text, bounds, integer] of checks) {
    const message = checkNumber(text, bounds, integer)
    if (message) errors[field] = message
  }
  if (account && resolveIdentifier(form.device, builder.devices, account.device_id) === null) {
    errors.device = 'This account has no device of its own yet. Choose another device.'
  }
  if (account && !isCod(form.payment) && resolveIdentifier(form.token, builder.tokens, account.payment_token_id) === null) {
    errors.token = 'This account has no payment token of its own yet. Choose another.'
  }
  return errors
}

const HEX = '0123456789ABCDEF'
const ORDER_SUFFIX_LENGTH = 8

/** `ORD-TRY-` and 8 random upper-case hex characters. */
export function newOrderId(random: (n: number) => Uint8Array = (n) => crypto.getRandomValues(new Uint8Array(n))): string {
  const bytes = random(ORDER_SUFFIX_LENGTH)
  return `ORD-TRY-${Array.from(bytes, (b) => HEX[b % HEX.length]).join('')}`
}

/** The request the checkout receives. Call only after `validate` returned no errors. */
export function buildRequest(form: TryForm, builder: OrderBuilderResponse, orderId: string): ScoreOrderRequest {
  const account = builder.accounts.find((a) => a.account_id === form.accountId)
  if (!account || form.category === '') throw new Error('buildRequest called on an invalid form')
  const category = form.category
  const sizes = SIZES.slice(0, Number(form.sizes))
  const device = resolveIdentifier(form.device, builder.devices, account.device_id)
  const token = isCod(form.payment) ? null : resolveIdentifier(form.token, builder.tokens, account.payment_token_id)
  if (device === null || (!isCod(form.payment) && token === null)) {
    throw new Error('buildRequest called without an identifier')
  }
  return {
    order_id: orderId,
    account_id: account.account_id,
    placed_at: builder.placed_at,
    lines: sizes.map((size, i) => ({
      sku_id: `SKU-TRY-${category}-${i + 1}`,
      product_id: `PRD-TRY-${category}`,
      variant: size,
      category,
      unit_price_inr: Number(form.price),
      quantity: Number(form.quantity),
    })),
    discount_pct: Number(form.discount),
    delivery_speed: form.delivery,
    payment_method: form.payment,
    device_id: device,
    address_id: account.address_id,
    payment_token_id: token,
  }
}
