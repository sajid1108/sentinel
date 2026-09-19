/**
 * The only place the browser talks to the API. Every type comes from the generated `types.ts` (§A.1);
 * nothing here is hand-written. The internal key is injected by the Vite proxy, so no secret reaches
 * the bundle; the reviewer identity is the placeholder `X-Reviewer-Id` header (§2).
 */
import type { components } from './types'

const API_BASE = '/api/v1'
const INTERNAL = `${API_BASE}/internal`

export type OrderDetailResponse = components['schemas']['OrderDetailResponse']
export type PolicyAssumptionsResponse = components['schemas']['PolicyAssumptionsResponse']
export type AuditVerifyResponse = components['schemas']['AuditVerifyResponse']
export type OverrideRequest = components['schemas']['OverrideRequest']
export type OverrideResponse = components['schemas']['OverrideResponse']
export type AppealRequest = components['schemas']['AppealRequest']
export type AuditEventOut = components['schemas']['AuditEventOut']
export type QueueResponse = components['schemas']['QueueResponse']
export type QueueItem = components['schemas']['QueueItem']
export type ScoreOrderRequest = components['schemas']['ScoreOrderRequest']
export type ScoreOrderResponse = components['schemas']['ScoreOrderResponse']
export type DemoResetResponse = components['schemas']['DemoResetResponse']
export type MetricsResponse = components['schemas']['MetricsResponse']
export type HealthResponse = components['schemas']['HealthResponse']

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(`API error ${status}: ${detail}`)
    this.name = 'ApiError'
  }
}

/** The server's 422 body lists where and why, never the submitted value (#34). */
type ValidationDetail = { loc?: string[]; msg?: string; type?: string }

function messageFrom(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const parts = (detail as ValidationDetail[])
      .map((e) => {
        const field = (e.loc ?? []).filter((p) => p !== 'body').join('.')
        return field ? `${field}: ${e.msg ?? ''}`.trim() : (e.msg ?? '')
      })
      .filter(Boolean)
    if (parts.length > 0) return parts.join('; ')
  }
  return fallback
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const detail = body === null ? res.statusText : (body as { detail?: unknown }).detail
    throw new ApiError(res.status, messageFrom(detail, res.statusText))
  }
  return res.json() as Promise<T>
}

export function getOrderDetail(orderId: string): Promise<OrderDetailResponse> {
  return apiFetch<OrderDetailResponse>(`/internal/orders/${encodeURIComponent(orderId)}`)
}

export function getPolicyAssumptions(): Promise<PolicyAssumptionsResponse> {
  return apiFetch<PolicyAssumptionsResponse>('/internal/policy')
}

export function verifyAuditChain(): Promise<AuditVerifyResponse> {
  return apiFetch<AuditVerifyResponse>('/internal/audit-events/verify')
}

export function postOverride(
  orderId: string,
  body: OverrideRequest,
  reviewerId: string,
): Promise<OverrideResponse> {
  return apiFetch<OverrideResponse>(`/internal/orders/${encodeURIComponent(orderId)}/override`, {
    method: 'POST',
    headers: { 'X-Reviewer-Id': reviewerId },
    body: JSON.stringify(body),
  })
}

export function postAppeal(
  orderId: string,
  body: AppealRequest,
  reviewerId: string,
): Promise<AuditEventOut> {
  return apiFetch<AuditEventOut>(`/internal/orders/${encodeURIComponent(orderId)}/appeal`, {
    method: 'POST',
    headers: { 'X-Reviewer-Id': reviewerId },
    body: JSON.stringify(body),
  })
}

/** GET /internal/orders. The caller owns the query string, which is also the page's URL state (§A). */
export function getQueue(query: string): Promise<QueueResponse> {
  return apiFetch<QueueResponse>(`/internal/orders${query ? `?${query}` : ''}`)
}

/** GET /health, for the policy version the Overview labels the backtest with (#7). Not under /api/v1. */
export async function getHealth(): Promise<HealthResponse> {
  const res = await fetch('/health')
  if (!res.ok) throw new ApiError(res.status, res.statusText)
  return res.json() as Promise<HealthResponse>
}

export function getMetrics(): Promise<MetricsResponse> {
  return apiFetch<MetricsResponse>('/internal/metrics')
}

/**
 * GET /internal/demo/presets. 404 when DEMO_MODE is off, and the panel then does not render at all
 * (§B) — so the 404 is an ordinary answer here, not an error to report.
 */
export function getPresets(): Promise<ScoreOrderRequest[]> {
  return apiFetch<ScoreOrderRequest[]>('/internal/demo/presets')
}

/**
 * POST /internal/demo/presets/{order_id}/score: the server scores its own preset and records it as DEMO
 * (Phase 10 Part 1). No body is sent, so what is scored is exactly what the server offered. Idempotent.
 */
export function postScorePreset(orderId: string): Promise<ScoreOrderResponse> {
  return apiFetch<ScoreOrderResponse>(`/internal/demo/presets/${encodeURIComponent(orderId)}/score`, {
    method: 'POST',
  })
}

export function postDemoReset(): Promise<DemoResetResponse> {
  return apiFetch<DemoResetResponse>('/internal/demo/reset', { method: 'POST' })
}

export { INTERNAL }
