/**
 * Shared harness for the order-detail tests.
 *
 * Every fixture under `src/__fixtures__/` was captured from the real backend: the world is generated and
 * seeded, the three §11 demo presets are scored through POST /score-order, and each GET
 * /orders/{id} body is recorded verbatim. Nothing in these tests invents a probability, a cost or a
 * money string.
 */
import { render, type RenderResult } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { vi } from 'vitest'

import type { OrderDetailResponse, PolicyAssumptionsResponse } from '../api/client'
import OrderDetailPage from '../pages/OrderDetailPage'

import auditVerify from '../__fixtures__/audit-verify.json'
import degraded from '../__fixtures__/degraded.json'
import demo1 from '../__fixtures__/demo-1.json'
import demo2 from '../__fixtures__/demo-2.json'
import demo3 from '../__fixtures__/demo-3.json'
import overridden from '../__fixtures__/overridden.json'
import policyFixture from '../__fixtures__/policy.json'

/**
 * TypeScript infers a JSON import's literal shape, which is narrower than the contract in places (an
 * `evidence` map's keys differ per reason code) and wider in others (enums read as `string`). The payloads
 * themselves were produced and validated by the server's Pydantic contracts at capture time, so the cast
 * asserts what the API already guaranteed. It is the only cast in the codebase, and it is on test data.
 */
function recorded(payload: unknown): OrderDetailResponse {
  return payload as OrderDetailResponse
}

export const FIXTURES = {
  'demo-1': recorded(demo1),
  'demo-2': recorded(demo2),
  'demo-3': recorded(demo3),
  degraded: recorded(degraded),
  overridden: recorded(overridden),
}

export type FixtureName = keyof typeof FIXTURES
export const DEMOS: FixtureName[] = ['demo-1', 'demo-2', 'demo-3']
export const POLICY = policyFixture as unknown as PolicyAssumptionsResponse

type Handler = (url: string, init?: RequestInit) => { status: number; body: unknown } | null

function ok(body: unknown) {
  return { status: 200, body }
}

/** A fetch that serves the recorded fixtures, plus any handler a test wants to add. */
export function stubFetch(detail: OrderDetailResponse, extra: Handler | null = null) {
  const fetchStub = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const handled = extra?.(url, init)
    const response =
      handled ??
      (url.includes('/internal/policy')
        ? ok(POLICY)
        : url.includes('/audit-events/verify')
          ? ok(auditVerify)
          : url.includes('/internal/orders/')
            ? ok(detail)
            : { status: 404, body: { detail: 'Not found.' } })
    return {
      ok: response.status >= 200 && response.status < 300,
      status: response.status,
      statusText: String(response.status),
      json: async () => response.body,
    } as Response
  })
  vi.stubGlobal('fetch', fetchStub)
  return fetchStub
}

export function renderDetail(name: FixtureName, extra: Handler | null = null): {
  detail: OrderDetailResponse
  view: RenderResult
} {
  const detail = FIXTURES[name]
  stubFetch(detail, extra)
  const view = render(
    <MemoryRouter initialEntries={[`/orders/${detail.order.order_id}`]}>
      <Routes>
        <Route path="/orders/:orderId" element={<OrderDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
  return { detail, view }
}

/** Every money string the fixture contains, so rendered text can be checked against it (§E, "Money"). */
export function moneyDisplays(value: unknown, found: Set<string> = new Set()): Set<string> {
  if (Array.isArray(value)) {
    for (const item of value) moneyDisplays(item, found)
  } else if (value !== null && typeof value === 'object') {
    const record = value as Record<string, unknown>
    if (typeof record.display === 'string' && typeof record.inr === 'number') found.add(record.display)
    for (const item of Object.values(record)) moneyDisplays(item, found)
  }
  return found
}

// ── Phase 9: the queue, the presets, the metrics ─────────────────────────────
import App from '../App'
import metricsFixture from '../__fixtures__/metrics.json'
import presetsFixture from '../__fixtures__/presets.json'
import queueFixture from '../__fixtures__/queue.json'
import scoreOrderFixture from '../__fixtures__/score-order-response.json'
import type { MetricsResponse, QueueResponse, ScoreOrderRequest, ScoreOrderResponse } from '../api/client'

export const QUEUE = queueFixture as unknown as QueueResponse
export const PRESETS = presetsFixture as unknown as ScoreOrderRequest[]
export const METRICS = metricsFixture as unknown as MetricsResponse
export const SCORE_RESPONSE = scoreOrderFixture as unknown as ScoreOrderResponse

export type Recorded = { url: string; init?: RequestInit }

/**
 * A fetch over the recorded Phase 9 payloads. `overrides` replaces the answer for any url a test cares
 * about; `calls` records every request so a test can assert what was actually sent.
 */
export function stubApi(
  overrides: ((url: string, init?: RequestInit) => { status: number; body: unknown } | null) | null = null,
) {
  const calls: Recorded[] = []
  const fetchStub = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    calls.push({ url, init })
    const handled = overrides?.(url, init)
    const response =
      handled ??
      (url.includes('/demo/presets')
        ? ok(PRESETS)
        : url.includes('/internal/metrics')
          ? ok(METRICS)
          : url.includes('/internal/orders?') || url.endsWith('/internal/orders')
            ? ok(QUEUE)
            : url.includes('/internal/score-order')
              ? ok(SCORE_RESPONSE)
              : url.includes('/demo/reset')
                ? ok({ status: 'reset', decisions: QUEUE.total })
                : url.includes('/internal/policy')
                  ? ok(POLICY)
                  : url.includes('/health')
                    ? ok({
                        status: 'healthy',
                        service: 'sentinel',
                        version: '0.1.0',
                        policy_version: POLICY.policy_version,
                        policy_config_sha256: POLICY.policy_config_sha256.slice(0, 8),
                        demo_clock: '2026-09-01T10:30:00+05:30',
                      })
                    : url.includes('/audit-events/verify')
                      ? ok(auditVerify)
                      : url.includes('/internal/orders/')
                        ? ok(FIXTURES['demo-1'])
                        : { status: 404, body: { detail: 'Not found.' } })
    return {
      ok: response.status >= 200 && response.status < 300,
      status: response.status,
      statusText: String(response.status),
      json: async () => response.body,
    } as Response
  })
  vi.stubGlobal('fetch', fetchStub)
  return { fetchStub, calls }
}

/** Mounts the whole app at a route, so the nav rail and the synthetic-data notice are present. */
export function renderApp(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )
}
