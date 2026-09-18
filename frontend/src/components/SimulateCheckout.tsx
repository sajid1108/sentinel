/**
 * "Simulate checkout" (§B) and "Reset demo" (§C), above the queue table.
 *
 * The panel exists only when `GET /internal/demo/presets` answers, which is only when DEMO_MODE is on;
 * a 404 renders nothing at all, reset button included. Every button is labelled from its own preset's
 * data — no demo id is special-cased and no label is written here — and a click posts the preset back
 * to the server byte for byte, so what is scored is exactly what the server offered.
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  ApiError,
  getPresets,
  postDemoReset,
  postScoreOrder,
  type ScoreOrderRequest,
} from '../api/client'
import { Panel } from './Panel'

export const RESET_CONFIRM_QUESTION =
  'This deletes every scored demo and live decision and rebuilds the database. Reset demo?'

/**
 * A preset's button label, read from the preset itself: its order id, the category of its first line,
 * and its payment method. §B forbids a per-preset label, so this must work for any request the server
 * sends, including one added later.
 */
export function presetLabel(preset: ScoreOrderRequest): string {
  const category = preset.lines[0]?.category ?? ''
  return [preset.order_id, sentence(category), sentence(preset.payment_method)].filter(Boolean).join(' · ')
}

function sentence(value: string): string {
  if (value === '') return ''
  const words = value.replace(/_/g, ' ').toLowerCase()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

type ResetState =
  | { kind: 'idle' }
  | { kind: 'confirming' }
  | { kind: 'running' }
  | { kind: 'done'; decisions: number }
  | { kind: 'failed'; message: string }

function ResetDemo({ onReset }: { onReset: () => void }) {
  const [state, setState] = useState<ResetState>({ kind: 'idle' })

  const confirm = () => {
    setState({ kind: 'running' })
    postDemoReset()
      .then((body) => {
        setState({ kind: 'done', decisions: body.decisions })
        onReset()
      })
      .catch((err: unknown) => {
        setState({
          kind: 'failed',
          message: err instanceof ApiError ? err.detail : 'The demo could not be reset.',
        })
      })
  }

  return (
    <div data-testid="reset-demo" className="mt-3 border-t border-slate-800 pt-3">
      {state.kind === 'confirming' ? (
        // An inline confirmation line, not a second modal (DESIGN.md §4).
        <div data-testid="reset-confirm" className="flex flex-wrap items-center gap-3">
          <p className="text-sm text-slate-200">{RESET_CONFIRM_QUESTION}</p>
          <button
            type="button"
            onClick={confirm}
            className="rounded border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 transition-colors duration-150 hover:bg-slate-700"
          >
            Confirm
          </button>
          <button
            type="button"
            onClick={() => setState({ kind: 'idle' })}
            className="rounded border border-slate-700 px-3 py-1.5 text-sm text-slate-300 transition-colors duration-150 hover:bg-slate-800"
          >
            Cancel
          </button>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            data-testid="reset-demo-button"
            disabled={state.kind === 'running'}
            onClick={() => setState({ kind: 'confirming' })}
            className="rounded border border-slate-700 px-3 py-1.5 text-sm text-slate-300 transition-colors duration-150 hover:bg-slate-800 disabled:opacity-50"
          >
            {state.kind === 'running' ? 'Resetting…' : 'Reset demo'}
          </button>
          {state.kind === 'done' && (
            <span data-testid="reset-result" className="text-sm text-slate-400">
              Demo reset: {state.decisions} decisions
            </span>
          )}
          {state.kind === 'failed' && (
            <span data-testid="reset-error" className="text-sm text-error">
              {state.message}
            </span>
          )}
        </div>
      )}
    </div>
  )
}

export function SimulateCheckout({ onReset }: { onReset: () => void }) {
  const [presets, setPresets] = useState<ScoreOrderRequest[] | null>(null)
  const [scoring, setScoring] = useState<string | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const navigate = useNavigate()

  useEffect(() => {
    let cancelled = false
    getPresets()
      .then((body) => {
        if (!cancelled) setPresets(body)
      })
      .catch(() => {
        // 404 means DEMO_MODE is off. There is nothing to show and nothing to report.
        if (!cancelled) setPresets(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (presets === null || presets.length === 0) return null

  const score = (preset: ScoreOrderRequest) => {
    setScoring(preset.order_id)
    setErrors((previous) => {
      const { [preset.order_id]: _removed, ...rest } = previous
      return rest
    })
    // The preset goes back unmodified. Scoring is idempotent per order, so a second click on the same
    // button is a replay and simply navigates again.
    postScoreOrder(preset)
      .then((response) => {
        setScoring(null)
        navigate(`/orders/${encodeURIComponent(response.order_id)}`)
      })
      .catch((err: unknown) => {
        setScoring(null)
        setErrors((previous) => ({
          ...previous,
          [preset.order_id]:
            err instanceof ApiError ? err.detail : 'The order could not be scored.',
        }))
      })
  }

  return (
    <Panel
      title="Simulate checkout"
      subtitle="Scores a preset order through the real models and the real policy, then opens its decision."
    >
      <ul data-testid="preset-list" className="space-y-2">
        {presets.map((preset) => (
          <li key={preset.order_id} className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              data-testid={`preset-${preset.order_id}`}
              disabled={scoring === preset.order_id}
              onClick={() => score(preset)}
              className="rounded border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 transition-colors duration-150 hover:bg-slate-700 disabled:opacity-50"
            >
              {scoring === preset.order_id ? 'Scoring…' : presetLabel(preset)}
            </button>
            {errors[preset.order_id] && (
              <span data-testid={`preset-error-${preset.order_id}`} className="text-sm text-error">
                {errors[preset.order_id]}
              </span>
            )}
          </li>
        ))}
      </ul>
      <ResetDemo onReset={onReset} />
    </Panel>
  )
}
