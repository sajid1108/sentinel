/**
 * The order-detail page against recorded payloads from the real backend (§E).
 *
 * These tests exist to catch the two failure modes that would cost the demo its credibility: a number on
 * the page that the API did not produce, and the two probabilities being treated as one risk score.
 */
import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { render } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import OrderDetailPage from '../pages/OrderDetailPage'
import { ACTION_LABEL, ACTION_ORDER, REASON_LABEL } from '../lib/actions'
import { FLAG_LABEL } from '../components/RelationshipGraph'
import { DEMOS, FIXTURES, POLICY, moneyDisplays, renderDetail, stubFetch, type FixtureName } from './render'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function open(name: FixtureName) {
  const rendered = renderDetail(name)
  await screen.findByTestId('abuse-score-card')
  return rendered
}

// ── scores ───────────────────────────────────────────────────────────────────
describe('score cards', () => {
  it.each(DEMOS)('%s renders two separate meters on two separate cards', async (name) => {
    await open(name)
    const returnCard = screen.getByTestId('return-score-card')
    const abuseCard = screen.getByTestId('abuse-score-card')
    expect(returnCard).toBeInTheDocument()
    expect(abuseCard).toBeInTheDocument()
    // Two meters, one owned by each card: neither is inside the other, so they cannot share a scale.
    const meters = screen.getAllByRole('meter')
    expect(meters).toHaveLength(2)
    expect(within(returnCard).getAllByRole('meter')).toHaveLength(1)
    expect(within(abuseCard).getAllByRole('meter')).toHaveLength(1)
    expect(returnCard.contains(abuseCard)).toBe(false)
    expect(abuseCard.contains(returnCard)).toBe(false)
  })

  it.each(DEMOS)('%s shows each probability under its own heading and nowhere combined', async (name) => {
    const { detail } = await open(name)
    const scores = detail.decision.scores
    const pReturn = scores.p_return
    const pAbuse = scores.p_abuse
    expect(pReturn).not.toBeNull()
    expect(pAbuse).not.toBeNull()
    // No element anywhere renders a combined score: neither the mean nor the sum appears as a percentage.
    // A combined value that happens to render identically to one of the two real scores proves nothing, so
    // it is skipped (Demo 1's p_abuse is small enough that p_return + p_abuse rounds to p_return).
    const asPercent = (value: number) => `${(value * 100).toFixed(1)}%`
    const own = new Set([asPercent(pReturn ?? 0), asPercent(pAbuse ?? 0)])
    const combined = [((pReturn ?? 0) + (pAbuse ?? 0)) / 2, (pReturn ?? 0) + (pAbuse ?? 0)]
      .map(asPercent)
      .filter((value) => !own.has(value))
    expect(combined.length).toBeGreaterThan(0)
    const text = document.body.textContent ?? ''
    for (const forbidden of combined) expect(text).not.toContain(forbidden)
  })

  it('the return card never uses a red class or the BLOCK colour', async () => {
    for (const name of DEMOS) {
      await open(name)
      const card = screen.getByTestId('return-score-card')
      // Markup only: reviewer text legitimately contains words like "returned".
      const markup = [...card.querySelectorAll('*'), card]
        .flatMap((el) => [el.getAttribute('class') ?? '', el.getAttribute('style') ?? ''])
        .join(' ')
      expect(markup).not.toMatch(/red/i)
      expect(markup).not.toContain('--color-block')
      expect(markup).toContain('--color-return')
      cleanup()
    }
  })

  it('Demo 1’s abuse probability renders as <0.1%, never 0.0%', async () => {
    const { detail } = await open('demo-1')
    expect(detail.decision.scores.p_abuse).toBeLessThan(0.001)
    const card = screen.getByTestId('abuse-score-card')
    expect(within(card).getByText('<0.1%')).toBeInTheDocument()
    expect(card.textContent).not.toContain('0.0%')
  })

  it('Demo 2 captions the counterfactual with the without-graph probability', async () => {
    const { detail } = await open('demo-2')
    const withoutGraph = detail.decision.scores.p_abuse_without_graph_evidence
    expect(withoutGraph).not.toBeNull()
    const card = screen.getByTestId('abuse-score-card')
    expect(card.textContent).toContain('Without relationship evidence:')
    expect(card.textContent).toContain('counterfactual: relationship features set to typical values')
    expect(within(card).getByTestId('abuse-meter-ghost')).toBeInTheDocument()
  })
})

// ── money ────────────────────────────────────────────────────────────────────
describe('money', () => {
  it.each(DEMOS)('%s renders only money strings the server produced', async (name) => {
    const { detail } = await open(name)
    const allowed = moneyDisplays(detail)
    expect(allowed.size).toBeGreaterThan(0)
    // The server also writes rupee amounts into its own sentences (a guardrail's `detail`, a policy
    // explanation). Those are rendered verbatim too, so the payload's raw text is the second allowance.
    const payload = JSON.stringify(detail)
    const rendered = (document.body.textContent ?? '').match(/₹[\d,]+/g) ?? []
    expect(rendered.length).toBeGreaterThan(0)
    for (const value of rendered) {
      expect(allowed.has(value) || payload.includes(value), `${value} was not produced by the server`).toBe(true)
    }
  })
})

// ── cost chart ───────────────────────────────────────────────────────────────
describe('expected-cost comparison', () => {
  it.each(DEMOS)('%s lists the four actions in the fixed order', async (name) => {
    await open(name)
    const rows = ACTION_ORDER.map((action) => screen.getByTestId(`cost-row-${action}`))
    const order = rows.map((row) => row.getAttribute('data-testid'))
    expect(order).toEqual(ACTION_ORDER.map((action) => `cost-row-${action}`))
    // …and in document order, so position always means the same action.
    for (let i = 1; i < rows.length; i += 1) {
      expect(rows[i - 1].compareDocumentPosition(rows[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    }
  })

  it.each(DEMOS)('%s tags the selected bar and only that one', async (name) => {
    const { detail } = await open(name)
    const selected = detail.decision.policy.selected_action
    expect(screen.getByTestId(`selected-tag-${selected}`)).toBeInTheDocument()
    for (const action of ACTION_ORDER) {
      if (action !== selected) expect(screen.queryByTestId(`selected-tag-${action}`)).toBeNull()
    }
  })

  it('Demo 2 shows G5 on ALLOW and Demo 3 shows G3 on BLOCK', async () => {
    await open('demo-2')
    expect(screen.getByTestId('guardrail-chip-ALLOW-G5')).toBeInTheDocument()
    cleanup()
    await open('demo-3')
    expect(screen.getByTestId('guardrail-chip-BLOCK-G3')).toBeInTheDocument()
  })

  it.each(DEMOS)('%s shows a guardrail chip for every excluded_by entry the server sent', async (name) => {
    const { detail } = await open(name)
    for (const cost of detail.decision.policy.costs) {
      for (const id of cost.excluded_by) {
        const chip = screen.getByTestId(`guardrail-chip-${cost.action}-${id}`)
        const detailText = detail.decision.policy.guardrails.find((g) => g.guardrail_id === id)?.detail
        expect(chip).toHaveAttribute('title', detailText)
      }
    }
  })

  it.each(DEMOS)('%s renders the policy explanation verbatim', async (name) => {
    const { detail } = await open(name)
    expect(screen.getByTestId('policy-explanation')).toHaveTextContent(
      detail.decision.policy.policy_explanation,
    )
  })

  it('the degraded decision hides the chart and says why', async () => {
    await open('degraded')
    expect(screen.queryByTestId('cost-chart')).toBeNull()
    expect(screen.getByTestId('degraded-cost-notice')).toHaveTextContent(
      'Costs are not computed without a model score (degraded mode).',
    )
    expect(screen.getByTestId('degraded-notice')).toHaveTextContent('Degraded mode: no model score')
    expect(screen.getByTestId('abuse-score-card')).toHaveTextContent('No model score')
    expect(screen.getByTestId('return-score-card')).toHaveTextContent('No model score')
  })
})

// ── graph ────────────────────────────────────────────────────────────────────
describe('relationship graph', () => {
  it.each(DEMOS)('%s draws the fixture’s nodes and edges, and the legend', async (name) => {
    const { detail } = await open(name)
    await waitFor(() => {
      expect(screen.getAllByTestId('graph-node')).toHaveLength(detail.graph.nodes.length)
      expect(screen.getAllByTestId('graph-edge')).toHaveLength(detail.graph.edges.length)
    })
    expect(screen.getByTestId('graph-legend')).toBeInTheDocument()
  })

  it.each(DEMOS)('%s dashes exactly the edges the server did not count', async (name) => {
    const { detail } = await open(name)
    await waitFor(() =>
      expect(screen.getAllByTestId('graph-edge')).toHaveLength(detail.graph.edges.length),
    )
    const dashed = screen
      .getAllByTestId('graph-edge')
      .filter((edge) => edge.getAttribute('data-counted') === 'false')
      .map((edge) => edge.getAttribute('data-edge-id'))
      .sort()
    const expected = detail.graph.edges
      .filter((edge) => !edge.counted_as_evidence)
      .map((edge) => edge.id)
      .sort()
    expect(dashed).toEqual(expected)
  })

  it('Demo 2 prints the counts the graph actually draws', async () => {
    const { detail } = await open('demo-2')
    expect(detail.graph.truncated).toBe(false)
    expect(detail.graph.linked_orders_24h_shown).toBe(detail.decision.graph_summary.linked_orders_24h)
    const counts = screen.getByTestId('graph-counts')
    expect(counts).toHaveTextContent(`${detail.graph.linked_orders_24h_shown} linked orders in the last 24 h`)
    expect(counts).toHaveTextContent(`${detail.graph.confirmed_peers_shown} confirmed accounts on this device`)
  })

  it('an order with no linked account says so and still draws the current node', async () => {
    // Demo 1 does have one household peer, so the empty state is exercised on Demo 1 with that account and
    // its edges removed - the same payload shape the API returns for an account linked to nobody.
    const source = FIXTURES['demo-1']
    const linked = source.graph.nodes.filter((n) => n.kind === 'ACCOUNT' && n.state !== 'CURRENT')
    expect(linked).toHaveLength(1)
    const dropped = new Set(linked.map((n) => n.id))
    const detail = {
      ...source,
      graph: {
        ...source.graph,
        nodes: source.graph.nodes.filter((n) => !dropped.has(n.id)),
        edges: source.graph.edges.filter((e) => !dropped.has(e.source) && !dropped.has(e.target)),
      },
    }
    stubFetch(detail)
    render(
      <MemoryRouter initialEntries={[`/orders/${detail.order.order_id}`]}>
        <Routes>
          <Route path="/orders/:orderId" element={<OrderDetailPage />} />
        </Routes>
      </MemoryRouter>,
    )
    await screen.findByTestId('abuse-score-card')
    expect(screen.getByTestId('graph-empty-notice')).toHaveTextContent('No relationships found for this order')
    await waitFor(() => expect(screen.getAllByTestId('graph-node').length).toBeGreaterThan(0))
    expect(screen.getAllByTestId('graph-node').some((n) => n.getAttribute('data-node-state') === 'CURRENT')).toBe(
      true,
    )
  })

  it('Demo 1 does not claim there are no relationships when a household peer is linked', async () => {
    const { detail } = await open('demo-1')
    expect(detail.graph.nodes.some((node) => node.kind === 'ACCOUNT' && node.state !== 'CURRENT')).toBe(true)
    expect(screen.queryByTestId('graph-empty-notice')).toBeNull()
  })
})

// ── evidence vs attribution ──────────────────────────────────────────────────
describe('evidence and model attribution', () => {
  it('Demo 2 lists STRONG evidence first and sorts attribution by magnitude', async () => {
    const { detail } = await open('demo-2')
    const evidence = within(screen.getByTestId('evidence-list')).getAllByTestId('reason-row')
    const shown = evidence.map((row) => row.getAttribute('data-code'))
    const increasing = detail.decision.reasons.filter(
      (r) => r.model === 'ABUSE' && r.direction === 'INCREASES',
    )
    expect(shown).toEqual(increasing.map((r) => r.code))
    const strongCount = increasing.filter((r) => r.evidence_strength === 'STRONG').length
    expect(strongCount).toBeGreaterThan(0)
    expect(increasing.slice(0, strongCount).every((r) => r.evidence_strength === 'STRONG')).toBe(true)

    const attribution = within(screen.getByTestId('attribution-list')).getAllByTestId('attribution-row')
    const magnitudes = attribution.map((row) => {
      const code = row.getAttribute('data-code')
      const reason = detail.decision.reasons.find((r) => r.code === code)
      return Math.abs(reason?.attribution_pp ?? 0)
    })
    expect(magnitudes).toEqual([...magnitudes].sort((a, b) => b - a))
  })

  it('Demo 2 renders the redundancy note and never a summed attribution', async () => {
    const { detail } = await open('demo-2')
    const notes = detail.decision.reasons.map((r) => r.attribution_note).filter((note) => Boolean(note))
    expect(notes.length).toBeGreaterThan(0)
    for (const note of notes) expect(screen.getAllByText(note as string).length).toBeGreaterThan(0)

    const total = detail.decision.reasons.reduce((sum, r) => sum + (r.attribution_pp ?? 0), 0)
    const text = document.body.textContent ?? ''
    expect(text).not.toContain(`${total.toFixed(1)} pp`)
    expect(screen.getByTestId('attribution-list').parentElement?.textContent).toContain(
      'Contributions overlap and are not additive.',
    )
  })

  it.each(DEMOS)('%s lists RETURN reasons under the return card and nowhere else', async (name) => {
    const { detail } = await open(name)
    const returnReasons = detail.decision.reasons.filter((r) => r.model === 'RETURN')
    const card = screen.getByTestId('return-score-card')
    for (const reason of returnReasons) {
      expect(within(card).getByText(reason.reviewer_text)).toBeInTheDocument()
      expect(screen.getAllByText(reason.reviewer_text)).toHaveLength(1)
    }
    const evidence = screen.queryByTestId('evidence-list')
    if (evidence !== null) {
      const codes = within(evidence)
        .getAllByTestId('reason-row')
        .map((row) => row.getAttribute('data-code'))
      for (const reason of returnReasons) expect(codes).not.toContain(reason.code)
    }
  })

  it.each(DEMOS)('%s renders the prediction explanation verbatim at the top of Evidence', async (name) => {
    const { detail } = await open(name)
    expect(screen.getByTestId('prediction-explanation')).toHaveTextContent(
      detail.decision.prediction_explanation,
    )
  })
})

// ── overridden decision ──────────────────────────────────────────────────────
describe('an overridden decision', () => {
  it('says what the system recommended and shows the override in the timeline', async () => {
    const { detail } = await open('overridden')
    expect(detail.current_action).not.toBe(detail.decision.policy.selected_action)
    // 1.6: the frontend's own text uses the label, never the enum value.
    const recommended = screen.getByTestId('system-recommended')
    expect(recommended).toHaveTextContent(
      `System recommended: ${ACTION_LABEL[detail.decision.policy.selected_action]}`,
    )
    expect(recommended.textContent).not.toContain(detail.decision.policy.selected_action)
    const events = within(screen.getByTestId('audit-timeline')).getAllByTestId('audit-event')
    const types = events.map((event) => event.getAttribute('data-event-type'))
    expect(types).toContain('OVERRIDE_APPLIED')
    expect(types).toEqual(detail.audit_events.map((event) => event.event_type))
  })

  it('shows the chain badge from the verify endpoint', async () => {
    await open('demo-2')
    await waitFor(() => expect(screen.getByTestId('chain-badge')).toHaveTextContent('Chain verified ✓'))
  })

  it.each(DEMOS)('%s shows both baselines with the rule each fired', async (name) => {
    const { detail } = await open(name)
    for (const baseline of detail.baselines) {
      const row = screen.getByTestId(`baseline-${baseline.strategy}`)
      expect(row).toHaveTextContent(baseline.rule_fired)
      expect(row.querySelector(`[data-action="${baseline.action}"]`)).not.toBeNull()
    }
    expect(screen.getByTestId('baselines').parentElement?.textContent).toContain('For comparison only.')
  })
})

// ── override dialog ──────────────────────────────────────────────────────────
describe('override dialog', () => {
  beforeEach(() => {
    try {
      window.localStorage.clear()
    } catch {
      /* private window: the picker falls back to the first reviewer */
    }
  })

  it('keeps submit disabled until the reason reaches 15 characters', async () => {
    await open('demo-3')
    fireEvent.click(screen.getByText('Override'))
    const submit = await screen.findByTestId('override-submit')
    expect(submit).toBeDisabled()
    fireEvent.change(screen.getByTestId('override-text'), { target: { value: 'too short' } })
    expect(submit).toBeDisabled()
    fireEvent.change(screen.getByTestId('override-text'), {
      target: { value: 'Customer verified by support today.' },
    })
    expect(submit).toBeEnabled()
  })

  it('renders the reload message when the decision changed underneath (409)', async () => {
    renderDetail('demo-3', (url, init) =>
      url.includes('/override') && init?.method === 'POST'
        ? { status: 409, body: { detail: 'current action is MANUAL_REVIEW' } }
        : null,
    )
    await screen.findByTestId('abuse-score-card')
    fireEvent.click(screen.getByText('Override'))
    fireEvent.change(await screen.findByTestId('override-text'), {
      target: { value: 'Customer verified by support today.' },
    })
    fireEvent.click(screen.getByTestId('override-submit'))
    const conflict = await screen.findByTestId('override-conflict')
    expect(conflict).toHaveTextContent('This order was changed by someone else. Reload to see the latest.')
    expect(within(conflict).getByText('Reload')).toBeInTheDocument()
  })

  it('shows the server message beside the field on 422', async () => {
    renderDetail('demo-3', (url, init) =>
      url.includes('/override') && init?.method === 'POST'
        ? {
            status: 422,
            body: { detail: [{ loc: ['body', 'reason_text'], msg: 'String should have at least 15 characters' }] },
          }
        : null,
    )
    await screen.findByTestId('abuse-score-card')
    fireEvent.click(screen.getByText('Override'))
    fireEvent.change(await screen.findByTestId('override-text'), {
      target: { value: 'Customer verified by support today.' },
    })
    fireEvent.click(screen.getByTestId('override-submit'))
    expect(await screen.findByTestId('override-field-error')).toHaveTextContent('reason_text')
  })

  it('sends expected_current_action and the reviewer header, then shows the returned warnings', async () => {
    const sent: { body: unknown; headers: unknown }[] = []
    const fetches: string[] = []
    renderDetail('demo-2', (url, init) => {
      fetches.push(url)
      if (!url.includes('/override') || init?.method !== 'POST') return null
      sent.push({ body: JSON.parse(String(init.body)), headers: init.headers })
      return {
        status: 200,
        body: {
          order_id: 'ORD-DEMO-002',
          decision_id: 'd',
          original_recommendation: 'BLOCK',
          previous_action: 'BLOCK',
          new_action: 'ALLOW',
          reviewer_id: 'reviewer-placeholder-01',
          overridden_at: '2026-09-01T05:10:00Z',
          audit_event_id: 'e',
          warnings: ['Override to ALLOW recorded.'],
        },
      }
    })
    await screen.findByTestId('abuse-score-card')
    fireEvent.click(screen.getByText('Override'))
    fireEvent.change(await screen.findByTestId('override-text'), {
      target: { value: 'Verified with the customer over the phone.' },
    })
    fireEvent.click(screen.getByTestId('override-submit'))
    await screen.findByTestId('override-applied')
    expect(screen.getByTestId('override-warnings')).toHaveTextContent('Override to ALLOW recorded.')
    // The detail refetches underneath, so the warnings survive: the page must not blank the dialog away.
    await waitFor(() => expect(fetches.filter((url) => url.includes('/internal/orders/')).length).toBeGreaterThan(1))
    expect(screen.getByTestId('override-applied')).toBeInTheDocument()
    const body = sent[0].body as { expected_current_action: string }
    expect(body.expected_current_action).toBe(FIXTURES['demo-2'].current_action)
    expect((sent[0].headers as Record<string, string>)['X-Reviewer-Id']).toMatch(/^reviewer-placeholder-0\d$/)
  })
})

// ── states ───────────────────────────────────────────────────────────────────
describe('page states', () => {
  it('shows a not-found message with a link back to the queue on 404', async () => {
    renderDetail('demo-1', (url) =>
      url.includes('/internal/orders/') ? { status: 404, body: { detail: 'Not found.' } } : null,
    )
    expect(await screen.findByText('Order not found')).toBeInTheDocument()
    expect(screen.getByText('Back to the queue')).toHaveAttribute('href', '/queue')
  })

  it('shows a retry button on an API error', async () => {
    renderDetail('demo-1', (url) =>
      url.includes('/internal/orders/')
        ? { status: 500, body: { detail: 'Something went wrong.' } }
        : null,
    )
    expect(await screen.findByText('Retry')).toBeInTheDocument()
    expect(screen.getByText('Something went wrong.')).toBeInTheDocument()
  })
})

// ── Phase 9 Part 1 follow-ups ────────────────────────────────────────────────
describe('1.1 the abuse meter is neutral', () => {
  it('fills identically on Demo 1, 2 and 3, whatever the score', async () => {
    const fills: string[] = []
    const scores: number[] = []
    for (const name of DEMOS) {
      const { detail } = await open(name)
      fills.push(screen.getByTestId('abuse-meter-fill').getAttribute('style') ?? '')
      scores.push(detail.decision.scores.p_abuse ?? -1)
      cleanup()
    }
    // The three scores really do straddle the band that used to turn the meter red, so an identical
    // fill colour across them is evidence the band is gone, not evidence it was never reached. The
    // threshold is read from the recorded policy payload, never written here.
    const blockMin = POLICY.sections
      .find((s) => s.section === 'guardrails')
      ?.values.find((v) => v.key === 'block_min_p_abuse')?.value
    expect(typeof blockMin).toBe('number')
    expect(Math.min(...scores)).toBeLessThan(blockMin as number)
    expect(Math.max(...scores)).toBeGreaterThanOrEqual(blockMin as number)
    const colours = fills.map((style) => /background-color:\s*([^;]+)/.exec(style)?.[1]?.trim())
    expect(colours.every((c) => c !== undefined && c === colours[0])).toBe(true)
  })

  it.each(DEMOS)('%s paints the abuse meter with no action colour', async (name) => {
    await open(name)
    const card = screen.getByTestId('abuse-score-card')
    const markup = [...card.querySelectorAll('*'), card]
      .flatMap((el) => [el.getAttribute('class') ?? '', el.getAttribute('style') ?? ''])
      .join(' ')
    for (const token of ['--color-block', '--color-review', '--color-prepaid', '--color-allow']) {
      expect(markup).not.toContain(token)
    }
    expect(markup).not.toMatch(/red|amber/i)
  })

  it('still marks the without-relationship-evidence counterfactual', async () => {
    await open('demo-2')
    expect(screen.getByTestId('abuse-meter-ghost')).toBeInTheDocument()
  })
})

describe('1.5 timestamps are in the demo’s timezone', () => {
  it('renders Demo 1’s placed-at as 10:25 IST under TZ=UTC', async () => {
    expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe('UTC')
    const { detail } = await open('demo-1')
    // The preset is placed at 2026-09-01T10:25:00+05:30; the browser's zone must not move it.
    expect(detail.order.placed_at).toContain('04:55')
    const placed = screen.getByText(/10:25/)
    expect(placed.textContent).toContain('IST')
    expect(placed.textContent).not.toContain('4:55')
  })

  it.each(DEMOS)('%s suffixes every rendered timestamp with IST', async (name) => {
    await open(name)
    const times = within(screen.getByTestId('audit-timeline')).getAllByText(/\d{1,2}:\d{2}\s*(am|pm)/i)
    expect(times.length).toBeGreaterThan(0)
    for (const time of times) expect(time.textContent).toContain('IST')
  })
})

describe('1.6 actions and reasons read as labels', () => {
  it('writes the override transition with labels, not enum values', async () => {
    const { detail } = await open('overridden')
    const override = within(screen.getByTestId('audit-timeline'))
      .getAllByTestId('audit-event')
      .find((e) => e.getAttribute('data-event-type') === 'OVERRIDE_APPLIED')
    expect(override).toBeDefined()
    const text = override?.textContent ?? ''
    expect(text).toContain(`${ACTION_LABEL.MANUAL_REVIEW} → ${ACTION_LABEL.PREPAID_ONLY}`)
    expect(text).not.toContain('MANUAL_REVIEW')
    expect(text).not.toContain('PREPAID_ONLY')
    // The override's reason category is humanised too.
    const category = (detail.audit_events.find((e) => e.event_type === 'OVERRIDE_APPLIED')
      ?.payload as { override?: { reason_category?: string } })?.override?.reason_category
    expect(category).toBeDefined()
    expect(text).toContain(REASON_LABEL[category as string])
    expect(text).not.toContain(category)
  })

  it.each(DEMOS)('%s still renders the server’s own sentences verbatim', async (name) => {
    const { detail } = await open(name)
    // 1.6 rewrites text the frontend controls. A server sentence is rendered as the server wrote it,
    // action enum names included, because it is the record.
    const explanation = detail.decision.policy.policy_explanation
    expect(screen.getByTestId('policy-explanation')).toHaveTextContent(explanation)
  })
})

describe('1.8 order nodes carry no per-node recency badge', () => {
  it('Demo 2 draws linked orders flagged RECENT_24H and shows no badge for it', async () => {
    const { detail } = await open('demo-2')
    const flagged = detail.graph.nodes.filter(
      (n) => n.kind === 'ORDER' && n.flags.includes('RECENT_24H'),
    )
    expect(flagged.length).toBeGreaterThan(0)
    const orderBadges = screen
      .getAllByTestId('graph-node')
      .filter((n) => n.getAttribute('data-node-kind') === 'ORDER')
      .flatMap((n) => [...n.querySelectorAll('[data-testid="graph-flag"]')].map((b) => b.textContent))
    expect(orderBadges).not.toContain(FLAG_LABEL.RECENT_24H)
    // Linked ACCOUNT nodes keep the badge: there it means the account placed an order in the window,
    // which the legend's order swatch does not say. 1.8 is about ORDER nodes only.
    const accountBadges = screen
      .getAllByTestId('graph-node')
      .filter((n) => n.getAttribute('data-node-kind') === 'ACCOUNT')
      .flatMap((n) => [...n.querySelectorAll('[data-testid="graph-flag"]')].map((b) => b.textContent))
    expect(accountBadges).toContain(FLAG_LABEL.RECENT_24H)
  })

  it('the legend says it once instead', async () => {
    await open('demo-2')
    const legend = screen.getByTestId('graph-legend')
    expect(legend).toHaveTextContent('Order placed in the last 24 h')
  })
})
