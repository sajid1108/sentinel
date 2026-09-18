/**
 * The Overview, against a `GET /metrics` payload recorded from the real backend (§E).
 *
 * The failure mode this exists to catch is an honesty one: the two sections answer different questions
 * from different sources (§Appendix A, C8), and the backtest table must show plainly that the tuned
 * fixed-threshold baseline beats Sentinel on realized cost rather than dressing Sentinel as the winner.
 */
import { cleanup, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { DATA_NOTICE } from '../components/SyntheticDataBanner'
import { ACTIVITY_LABEL, BACKTEST_LABEL, COST_AVOIDED_LABEL } from '../pages/OverviewPage'
import { METRICS, POLICY, PRESETS, renderApp, stubApi } from './render'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function openOverview(
  overrides: ((url: string, init?: RequestInit) => { status: number; body: unknown } | null) | null = null,
) {
  const api = stubApi(overrides)
  const view = renderApp('/')
  await screen.findByTestId('backtest-table')
  return { ...api, view }
}

const STRATEGY_ORDER = ['SENTINEL', 'FIXED_THRESHOLD', 'RULE_BASED', 'ALLOW_ALL']

describe('the two sections are separate and say what they are', () => {
  it('labels decision activity as counted by system recommendation', async () => {
    await openOverview()
    expect(screen.getByTestId('activity-label')).toHaveTextContent(ACTIVITY_LABEL)
    expect(ACTIVITY_LABEL).toContain('system recommendation')
  })

  it('labels the backtest as realized cost against synthetic labels on TEST', async () => {
    await openOverview()
    const label = screen.getByTestId('backtest-label')
    expect(label).toHaveTextContent('realized cost against synthetic labels on the held-out TEST split')
    expect(label).toHaveTextContent('Monetary values are demonstration assumptions')
    expect(BACKTEST_LABEL).toContain('Synthetic backtest')
  })

  it('names the policy version from /health rather than writing one in', async () => {
    await openOverview()
    expect(screen.getByTestId('backtest-label')).toHaveTextContent(`policy ${POLICY.policy_version}`)
    expect(BACKTEST_LABEL).not.toContain(POLICY.policy_version)
  })

  it('keeps the figures and the table in two regions, neither inside the other', async () => {
    await openOverview()
    const activity = screen.getByTestId('activity-figures')
    const backtest = screen.getByTestId('backtest-table')
    expect(activity.contains(backtest)).toBe(false)
    expect(backtest.contains(activity)).toBe(false)
    // Each label belongs to its own section.
    expect(screen.getByTestId('activity-label')).toBeInTheDocument()
    expect(screen.getByTestId('backtest-label')).toBeInTheDocument()
  })
})

describe('decision activity', () => {
  it('renders every figure from the payload, money from its display string', async () => {
    await openOverview()
    const a = METRICS.activity
    expect(screen.getByTestId('orders-evaluated')).toHaveTextContent(String(a.orders_evaluated))
    expect(screen.getByTestId('friction-orders')).toHaveTextContent(String(a.friction_orders))
    expect(screen.getByTestId('manual-review-volume')).toHaveTextContent(String(a.manual_review_volume))
    expect(screen.getByTestId('weak-evidence-decisions')).toHaveTextContent(String(a.weak_evidence_decisions))
    expect(screen.getByTestId('cost-avoided')).toHaveTextContent(a.model_estimated_cost_avoided.display)
  })

  it('says the avoided cost is an estimate, not a realized saving', async () => {
    await openOverview()
    expect(screen.getByTestId('cost-avoided')).toHaveTextContent(COST_AVOIDED_LABEL)
    expect(COST_AVOIDED_LABEL).toContain('estimate, not realized')
  })

  it('renders the action distribution in the fixed action order', async () => {
    await openOverview()
    const items = within(screen.getByTestId('action-distribution')).getAllByRole('listitem')
    expect(items.map((i) => i.getAttribute('data-testid'))).toEqual(
      STRATEGY_ORDER.length > 0
        ? ['ALLOW', 'PREPAID_ONLY', 'MANUAL_REVIEW', 'BLOCK'].map((a) => `distribution-${a}`)
        : [],
    )
    for (const [action, count] of Object.entries(METRICS.activity.action_distribution)) {
      expect(screen.getByTestId(`distribution-${action}`)).toHaveTextContent(String(count))
    }
  })
})

describe('the synthetic backtest table', () => {
  it('lists the four strategies in the fixed order', async () => {
    await openOverview()
    const rows = screen.getAllByTestId('backtest-row')
    expect(rows.map((r) => r.getAttribute('data-strategy'))).toEqual(STRATEGY_ORDER)
  })

  it('gives every StrategyBacktest field a column', async () => {
    await openOverview()
    const fields = Object.keys(METRICS.backtest[0]).filter((k) => k !== 'strategy')
    const columns = [...screen.getAllByTestId('backtest-row')[0].querySelectorAll('td')].map((c) =>
      c.getAttribute('data-column'),
    )
    expect(new Set(columns)).toEqual(new Set(fields))
  })

  it('renders money verbatim from the server display strings', async () => {
    await openOverview()
    const allowed = new Set<string>()
    for (const row of METRICS.backtest) {
      for (const value of Object.values(row)) {
        if (value !== null && typeof value === 'object' && 'display' in value) {
          allowed.add((value as { display: string }).display)
        }
      }
    }
    const rendered = [...screen.getByTestId('backtest-table').querySelectorAll('td')]
      .map((c) => c.textContent ?? '')
      .filter((text) => text.includes('₹'))
    expect(rendered.length).toBeGreaterThan(0)
    for (const value of rendered) {
      expect(allowed.has(value), `${value} was not produced by the server`).toBe(true)
    }
  })

  it('shows the fixed-threshold baseline beating Sentinel on realized cost, plainly', async () => {
    await openOverview()
    const sentinel = METRICS.backtest.find((r) => r.strategy === 'SENTINEL')
    const fixed = METRICS.backtest.find((r) => r.strategy === 'FIXED_THRESHOLD')
    // The measurement this table must not hide (#25): the tuned baseline is cheaper.
    expect(fixed?.realized_cost_per_1000.inr).toBeLessThan(sentinel?.realized_cost_per_1000.inr as number)
    const row = screen.getAllByTestId('backtest-row').find((r) => r.getAttribute('data-strategy') === 'FIXED_THRESHOLD')
    expect(row).toHaveTextContent(fixed?.realized_cost_per_1000.display as string)
  })

  it('marks no row as best: every row carries the same classes and no action colour', async () => {
    await openOverview()
    const rows = screen.getAllByTestId('backtest-row')
    const classes = rows.map((r) => r.getAttribute('class'))
    expect(new Set(classes).size).toBe(1)
    const markup = rows
      .flatMap((r) => [r, ...r.querySelectorAll('*')])
      .flatMap((el) => [el.getAttribute('class') ?? '', el.getAttribute('style') ?? ''])
      .join(' ')
    for (const token of ['--color-block', '--color-review', '--color-prepaid', '--color-allow']) {
      expect(markup).not.toContain(token)
    }
    expect(markup).not.toMatch(/red|amber|teal|emerald|green/i)
    expect(screen.getByTestId('backtest-table').textContent).not.toMatch(/\bbest\b|winner|recommended/i)
  })

  it('puts the cold-start recall on one line under the table', async () => {
    await openOverview()
    const line = screen.getByTestId('cold-start-recall')
    expect(line).toHaveTextContent('Cold-start ring (R3, unseen in training): recall')
    expect(line).toHaveTextContent(`${(METRICS.cold_start_ring_recall * 100).toFixed(1)}%`)
  })
})

describe('overview states', () => {
  it('shows the server message and a retry on an API error', async () => {
    stubApi((url) =>
      url.includes('/internal/metrics') ? { status: 500, body: { detail: 'Metrics unavailable.' } } : null,
    )
    renderApp('/')
    await screen.findByTestId('overview-error')
    expect(screen.getByTestId('overview-error')).toHaveTextContent('Metrics unavailable.')
    expect(screen.getByTestId('overview-retry')).toBeInTheDocument()
  })
})

// ── every page carries the notice ────────────────────────────────────────────
describe('the synthetic-data notice', () => {
  it.each([
    ['/', 'backtest-table'],
    ['/queue', 'queue-table'],
    [`/orders/${PRESETS[0].order_id}`, 'abuse-score-card'],
  ])('renders verbatim on %s', async (path, ready) => {
    stubApi()
    renderApp(path)
    await screen.findByTestId(ready)
    expect(screen.getByText(DATA_NOTICE)).toBeInTheDocument()
  })
})
