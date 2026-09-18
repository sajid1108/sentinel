/**
 * The queue, the preset buttons and the demo reset, against payloads recorded from the real backend (§E).
 *
 * The failure modes these exist to catch: the two probabilities presented as one score, a number the API
 * did not produce, a count labelled as something it is not, and a destructive action that runs without
 * being confirmed.
 */
import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ACTION_ORDER } from '../lib/actions'
import { PAGE_SIZE } from '../lib/queue'
import { presetLabel, RESET_CONFIRM_QUESTION } from '../components/SimulateCheckout'
import { ACTION_FILTER_LABEL, COUNTS_LABEL, EMPTY_MESSAGE } from '../pages/QueuePage'
import { PRESETS, QUEUE, SCORE_RESPONSE, renderApp, stubApi } from './render'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function openQueue(
  overrides: ((url: string, init?: RequestInit) => { status: number; body: unknown } | null) | null = null,
  path = '/queue',
) {
  const api = stubApi(overrides)
  const view = renderApp(path)
  await screen.findByTestId('queue-table')
  return { ...api, view }
}

// ── the two probabilities ────────────────────────────────────────────────────
describe('the queue keeps the two probabilities apart', () => {
  it('gives each its own column heading', async () => {
    await openQueue()
    const headers = within(screen.getByTestId('queue-table'))
      .getAllByRole('columnheader')
      .map((h) => h.textContent)
    expect(headers).toContain('Return probability')
    expect(headers).toContain('Abuse probability')
    // One column each, and the headings are distinct: nothing labelled "risk score".
    expect(headers.filter((h) => h?.toLowerCase().includes('probability'))).toHaveLength(2)
    expect(headers.join(' ')).not.toMatch(/risk score|combined|overall score/i)
  })

  it('renders both values per row, from the payload, never combined', async () => {
    await openQueue()
    const rows = screen.getAllByTestId('queue-row')
    expect(rows.length).toBe(QUEUE.items.length)
    for (const item of QUEUE.items.slice(0, 10)) {
      const row = rows.find((r) => r.getAttribute('data-order-id') === item.order_id)
      expect(row).toBeDefined()
      const cells = within(row as HTMLElement)
      expect(cells.getByTestId('queue-p-return')).toBeInTheDocument()
      expect(cells.getByTestId('queue-p-abuse')).toBeInTheDocument()
    }
    // No row shows a combined figure. Scoped per row: across 50 rows a mean of one row's two scores
    // can legitimately equal another row's real probability, which would prove nothing.
    for (const item of QUEUE.items) {
      if (item.p_return === null || item.p_abuse === null) continue
      const row = rows.find((r) => r.getAttribute('data-order-id') === item.order_id) as HTMLElement
      const own = new Set([`${(item.p_return * 100).toFixed(1)}%`, `${(item.p_abuse * 100).toFixed(1)}%`])
      const combined = [(item.p_return + item.p_abuse) / 2, item.p_return + item.p_abuse]
        .map((v) => `${(Math.min(1, v) * 100).toFixed(1)}%`)
        .filter((v) => !own.has(v))
      const cells = [...row.querySelectorAll('td')].map((c) => c.textContent ?? '')
      for (const forbidden of combined) expect(cells).not.toContain(forbidden)
    }
  })

  it('never paints the return column red', async () => {
    await openQueue()
    const cells = screen.getAllByTestId('queue-p-return')
    expect(cells.length).toBeGreaterThan(0)
    for (const cell of cells) {
      const markup = `${cell.getAttribute('class') ?? ''} ${cell.getAttribute('style') ?? ''}`
      expect(markup).not.toMatch(/red/i)
      expect(markup).not.toContain('--color-block')
      expect(markup).not.toContain('text-block')
    }
  })

  it('a degraded row says "No model score" rather than inventing one', async () => {
    const degradedItem = { ...QUEUE.items[0], p_return: null, p_abuse: null, order_id: 'ORD-DEGRADED-1' }
    await openQueue((url) =>
      url.includes('/internal/orders?')
        ? { status: 200, body: { ...QUEUE, items: [degradedItem] } }
        : null,
    )
    const row = screen.getByTestId('queue-row')
    expect(within(row).getByTestId('queue-p-return')).toHaveTextContent('No model score')
    expect(within(row).getByTestId('queue-p-abuse')).toHaveTextContent('No model score')
  })
})

// ── money ────────────────────────────────────────────────────────────────────
describe('queue money', () => {
  it('renders order values verbatim from the server display strings', async () => {
    await openQueue()
    const allowed = new Set(QUEUE.items.map((i) => i.order_value.display))
    // Cell by cell: the table's own textContent runs one cell into the next, so "₹4,500" followed by
    // "61.5%" would read as "₹4,50061" and prove nothing.
    const rendered = [...screen.getByTestId('queue-table').querySelectorAll('td')]
      .map((c) => c.textContent ?? '')
      .filter((text) => text.includes('₹'))
    expect(rendered.length).toBeGreaterThan(0)
    for (const value of rendered) {
      expect(allowed.has(value), `${value} was not produced by the server`).toBe(true)
    }
  })
})

// ── counts and labels ────────────────────────────────────────────────────────
describe('the counts say which action they count', () => {
  it('labels the counts row and the action filter as the current action', async () => {
    await openQueue()
    // #34: the queue counts the action in effect now; /metrics counts the recommendation.
    expect(screen.getByTestId('counts-by-action')).toHaveTextContent(COUNTS_LABEL)
    expect(COUNTS_LABEL.toLowerCase()).toContain('current action')
    expect(ACTION_FILTER_LABEL).toBe('Current action (after review)')
    expect(screen.getByText(ACTION_FILTER_LABEL)).toBeInTheDocument()
  })

  it('renders the counts in the fixed action order, from the payload', async () => {
    await openQueue()
    const counts = within(screen.getByTestId('counts-by-action')).getAllByRole('listitem')
    expect(counts.map((c) => c.getAttribute('data-testid'))).toEqual(
      ACTION_ORDER.map((a) => `count-${a}`),
    )
    for (const action of ACTION_ORDER) {
      expect(screen.getByTestId(`count-${action}`)).toHaveTextContent(
        String(QUEUE.counts_by_action[action] ?? 0),
      )
    }
  })
})

// ── filters in the URL ───────────────────────────────────────────────────────
describe('filters live in the URL', () => {
  it('a filter change updates the query and refetches with it', async () => {
    const { calls } = await openQueue()
    fireEvent.change(screen.getByTestId('filter-action'), { target: { value: 'BLOCK' } })
    await waitFor(() => {
      expect(calls.some((c) => c.url.includes('action=BLOCK'))).toBe(true)
    })
    // The browser URL carries it too, so a reload keeps the filter.
    expect(window.location.search || document.location.search).toBeDefined()
    const queued = calls.filter((c) => c.url.includes('/internal/orders?'))
    const last = queued[queued.length - 1]
    expect(last.url).toContain('action=BLOCK')
    expect(last.url).toContain(`limit=${PAGE_SIZE}`)
  })

  it('reads its initial state from the query string', async () => {
    const { calls } = await openQueue(null, '/queue?action=MANUAL_REVIEW&sort=p_abuse_desc&status=PENDING_REVIEW')
    const first = calls.find((c) => c.url.includes('/internal/orders?'))
    expect(first?.url).toContain('action=MANUAL_REVIEW')
    expect(first?.url).toContain('sort=p_abuse_desc')
    expect(first?.url).toContain('status=PENDING_REVIEW')
    expect((screen.getByTestId('filter-action') as HTMLSelectElement).value).toBe('MANUAL_REVIEW')
    expect((screen.getByTestId('filter-sort') as HTMLSelectElement).value).toBe('p_abuse_desc')
  })

  it('offers every sort key the contract defines', async () => {
    await openQueue()
    const options = [...(screen.getByTestId('filter-sort') as HTMLSelectElement).options].map((o) => o.value)
    expect(options).toEqual(['scored_at_desc', 'p_abuse_desc', 'value_desc', 'exposure_desc'])
  })
})

// ── pagination and states ────────────────────────────────────────────────────
describe('pagination and states', () => {
  it('shows the range and pages forward by the page size', async () => {
    const { calls } = await openQueue()
    expect(screen.getByTestId('queue-range')).toHaveTextContent(
      `Showing 1–${QUEUE.items.length} of ${QUEUE.total}`,
    )
    expect(screen.getByTestId('page-previous')).toBeDisabled()
    fireEvent.click(screen.getByTestId('page-next'))
    await waitFor(() => {
      expect(calls.some((c) => c.url.includes(`offset=${PAGE_SIZE}`))).toBe(true)
    })
  })

  it('shows an empty state with a way back', async () => {
    await stubApi((url) =>
      url.includes('/internal/orders?')
        ? { status: 200, body: { ...QUEUE, items: [], total: 0 } }
        : null,
    )
    renderApp('/queue?action=BLOCK')
    await screen.findByTestId('queue-empty')
    expect(screen.getByTestId('queue-empty')).toHaveTextContent(EMPTY_MESSAGE)
    expect(screen.getByTestId('queue-empty-clear')).toBeInTheDocument()
  })

  it('shows the server message and a retry on an API error', async () => {
    let attempts = 0
    stubApi((url) => {
      if (!url.includes('/internal/orders?')) return null
      attempts += 1
      return attempts === 1 ? { status: 500, body: { detail: 'Queue unavailable.' } } : null
    })
    renderApp('/queue')
    await screen.findByTestId('queue-error')
    expect(screen.getByTestId('queue-error')).toHaveTextContent('Queue unavailable.')
    fireEvent.click(screen.getByTestId('queue-retry'))
    await screen.findByTestId('queue-table')
  })
})

// ── §B simulate checkout ─────────────────────────────────────────────────────
describe('simulate checkout', () => {
  it('labels each button from its own preset, never from a demo id', async () => {
    await openQueue()
    for (const preset of PRESETS) {
      const button = screen.getByTestId(`preset-${preset.order_id}`)
      expect(button).toHaveTextContent(preset.order_id)
      expect(button).toHaveTextContent(new RegExp(preset.lines[0].category, 'i'))
      expect(button).toHaveTextContent(new RegExp(preset.payment_method.replace(/_/g, ' '), 'i'))
      expect(button.textContent).toBe(presetLabel(preset))
    }
    // In the order the server returned them.
    const rendered = within(screen.getByTestId('preset-list'))
      .getAllByRole('button')
      .map((b) => b.getAttribute('data-testid'))
    expect(rendered).toEqual(PRESETS.map((p) => `preset-${p.order_id}`))
  })

  it('sends the preset body unmodified and opens the order the server returned', async () => {
    const { calls } = await openQueue()
    const preset = PRESETS[0]
    fireEvent.click(screen.getByTestId(`preset-${preset.order_id}`))
    await waitFor(() => {
      expect(calls.some((c) => c.url.includes('/internal/score-order'))).toBe(true)
    })
    const posted = calls.find((c) => c.url.includes('/internal/score-order'))
    expect(JSON.parse(String(posted?.init?.body))).toEqual(preset)
    // It navigates to the id the response carried, not to the id that was clicked.
    await waitFor(() => {
      expect(screen.queryByTestId('queue-table')).toBeNull()
    })
    expect(SCORE_RESPONSE.order_id).toBe(preset.order_id)
  })

  it('shows the server message beside the button and leaves the page usable', async () => {
    await openQueue((url) =>
      url.includes('/internal/score-order')
        ? { status: 422, body: { detail: 'placed_at is after the demo clock.' } }
        : null,
    )
    const preset = PRESETS[0]
    fireEvent.click(screen.getByTestId(`preset-${preset.order_id}`))
    await screen.findByTestId(`preset-error-${preset.order_id}`)
    expect(screen.getByTestId(`preset-error-${preset.order_id}`)).toHaveTextContent(
      'placed_at is after the demo clock.',
    )
    expect(screen.getByTestId('queue-table')).toBeInTheDocument()
    expect(screen.getByTestId(`preset-${preset.order_id}`)).not.toBeDisabled()
  })

  it('renders neither the panel nor the reset button when the presets 404', async () => {
    await openQueue((url) =>
      url.includes('/demo/presets') ? { status: 404, body: { detail: 'Not found.' } } : null,
    )
    expect(screen.queryByTestId('preset-list')).toBeNull()
    expect(screen.queryByTestId('reset-demo')).toBeNull()
    expect(screen.queryByTestId('reset-demo-button')).toBeNull()
    // The queue itself is unaffected.
    expect(screen.getByTestId('queue-table')).toBeInTheDocument()
  })
})

// ── §C reset demo ────────────────────────────────────────────────────────────
describe('reset demo', () => {
  it('confirms before it posts, and refetches the queue afterwards', async () => {
    const { calls } = await openQueue()
    fireEvent.click(screen.getByTestId('reset-demo-button'))

    // The confirmation comes first: nothing has been posted yet.
    expect(screen.getByTestId('reset-confirm')).toHaveTextContent(RESET_CONFIRM_QUESTION)
    expect(calls.some((c) => c.url.includes('/demo/reset'))).toBe(false)

    const before = calls.filter((c) => c.url.includes('/internal/orders?')).length
    fireEvent.click(screen.getByText('Confirm'))
    await waitFor(() => {
      expect(calls.some((c) => c.url.includes('/demo/reset'))).toBe(true)
    })
    expect(calls.find((c) => c.url.includes('/demo/reset'))?.init?.method).toBe('POST')
    await waitFor(() => {
      expect(calls.filter((c) => c.url.includes('/internal/orders?')).length).toBeGreaterThan(before)
    })
    await screen.findByTestId('reset-result')
    expect(screen.getByTestId('reset-result')).toHaveTextContent('Demo reset:')
  })

  it('cancel posts nothing', async () => {
    const { calls } = await openQueue()
    fireEvent.click(screen.getByTestId('reset-demo-button'))
    fireEvent.click(screen.getByText('Cancel'))
    expect(screen.queryByTestId('reset-confirm')).toBeNull()
    expect(calls.some((c) => c.url.includes('/demo/reset'))).toBe(false)
    expect(screen.getByTestId('reset-demo-button')).toBeInTheDocument()
  })
})
