// Types will be generated from FastAPI OpenAPI schema
// For now, define the core types manually

export type Action = 'ALLOW' | 'PREPAID_ONLY' | 'MANUAL_REVIEW' | 'BLOCK'

export interface Money {
  inr: number
  display: string
}

export interface QueueItem {
  order_id: string
  decision_id: string
  scored_at: string
  order_value: Money
  p_return: number
  p_abuse: number
  recommended_action: Action
  current_action: Action
  status: 'AUTO_APPLIED' | 'PENDING_REVIEW' | 'OVERRIDDEN' | 'APPEAL_OPEN'
  graph_risk_summary: string
  corroborating_signal_count: number
  source: 'DEMO' | 'BACKTEST_REPLAY' | 'LIVE'
}

export interface HealthResponse {
  status: string
  service: string
  version: string
  policy_version: string
  policy_config_sha256: string
  demo_clock: string
}
