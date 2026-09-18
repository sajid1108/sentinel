/**
 * Override and appeal dialogs (§C).
 *
 * The override sends `expected_current_action` automatically, so a decision someone else changed in the
 * meantime comes back 409 and the reviewer is told to reload rather than silently overwriting it (H1, §4).
 * The reason text must reach 15 characters, the same bound the server enforces; the count is live so the
 * reviewer is never guessing. Server warnings are shown as returned.
 */
import { useState, type ReactNode } from 'react'

import { ApiError, postAppeal, postOverride, type AppealRequest, type OverrideResponse } from '../api/client'
import { ACTION_LABEL, ACTION_ORDER, OVERRIDE_REASONS, REASON_LABEL, type Action } from '../lib/actions'

export const MIN_REASON_CHARS = 15
export const MIN_NOTE_CHARS = 10
export const CONFLICT_MESSAGE = 'This order was changed by someone else. Reload to see the latest.'

function Dialog({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: ReactNode
}) {
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/80 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="w-full max-w-lg rounded-lg border border-slate-700 bg-slate-900 shadow-2xl"
      >
        <header className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-100">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 transition-colors duration-150 hover:bg-slate-800"
          >
            Close
          </button>
        </header>
        <div className="p-4">{children}</div>
      </div>
    </div>
  )
}

const FIELD =
  'mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100 transition-colors duration-150 focus:border-slate-500 focus:outline-none'

export function OverrideDialog({
  orderId,
  currentAction,
  reviewerId,
  onClose,
  onApplied,
}: {
  orderId: string
  currentAction: Action
  reviewerId: string
  onClose: () => void
  onApplied: (response: OverrideResponse) => void
}) {
  const [newAction, setNewAction] = useState<Action>(currentAction)
  const [category, setCategory] = useState<(typeof OVERRIDE_REASONS)[number]>(OVERRIDE_REASONS[0])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [conflict, setConflict] = useState(false)
  const [fieldError, setFieldError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [warnings, setWarnings] = useState<string[] | null>(null)

  const tooShort = text.trim().length < MIN_REASON_CHARS

  async function submit() {
    setBusy(true)
    setConflict(false)
    setFieldError(null)
    setError(null)
    try {
      const response = await postOverride(
        orderId,
        {
          new_action: newAction,
          reason_category: category,
          reason_text: text.trim(),
          expected_current_action: currentAction,
        },
        reviewerId,
      )
      setWarnings(response.warnings)
      onApplied(response)
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 409) setConflict(true)
      else if (err instanceof ApiError && err.status === 422) setFieldError(err.detail)
      else setError(err instanceof ApiError ? err.detail : 'The override could not be recorded.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog title="Override the decision" onClose={onClose}>
      {conflict ? (
        <div data-testid="override-conflict">
          <p className="text-sm text-slate-100">{CONFLICT_MESSAGE}</p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-3 rounded border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 transition-colors duration-150 hover:bg-slate-700"
          >
            Reload
          </button>
        </div>
      ) : warnings !== null ? (
        <div data-testid="override-applied">
          <p className="text-sm text-slate-100">The override was recorded.</p>
          {warnings.length > 0 && (
            <ul data-testid="override-warnings" className="mt-2 space-y-1">
              {warnings.map((warning) => (
                <li key={warning} className="text-xs text-slate-300">
                  {warning}
                </li>
              ))}
            </ul>
          )}
          <button
            type="button"
            onClick={onClose}
            className="mt-3 rounded border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 transition-colors duration-150 hover:bg-slate-700"
          >
            Done
          </button>
        </div>
      ) : (
        <form
          onSubmit={(event) => {
            event.preventDefault()
            if (!tooShort && !busy) void submit()
          }}
        >
          <label className="block text-xs text-slate-400">
            New action
            <select
              data-testid="override-action"
              value={newAction}
              onChange={(event) => setNewAction(event.target.value as Action)}
              className={FIELD}
            >
              {ACTION_ORDER.map((action) => (
                <option key={action} value={action}>
                  {ACTION_LABEL[action]}
                </option>
              ))}
            </select>
          </label>

          <label className="mt-3 block text-xs text-slate-400">
            Reason category
            <select
              data-testid="override-category"
              value={category}
              onChange={(event) => setCategory(event.target.value as (typeof OVERRIDE_REASONS)[number])}
              className={FIELD}
            >
              {OVERRIDE_REASONS.map((reason) => (
                <option key={reason} value={reason}>
                  {REASON_LABEL[reason]}
                </option>
              ))}
            </select>
          </label>

          <label className="mt-3 block text-xs text-slate-400">
            Reason
            <textarea
              data-testid="override-text"
              value={text}
              rows={4}
              onChange={(event) => setText(event.target.value)}
              className={FIELD}
            />
          </label>
          <p data-testid="override-char-count" className="mt-1 text-xs text-slate-500">
            {text.trim().length} characters · minimum {MIN_REASON_CHARS}
          </p>
          {fieldError && (
            <p data-testid="override-field-error" className="mt-1 text-xs text-slate-200">
              {fieldError}
            </p>
          )}
          {error && <p className="mt-2 text-xs text-slate-200">{error}</p>}

          <div className="mt-4 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded border border-slate-700 px-3 py-1.5 text-sm text-slate-300 transition-colors duration-150 hover:bg-slate-800"
            >
              Cancel
            </button>
            <button
              type="submit"
              data-testid="override-submit"
              disabled={tooShort || busy}
              className="rounded border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 transition-colors duration-150 hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Record override
            </button>
          </div>
        </form>
      )}
    </Dialog>
  )
}

export function AppealDialog({
  orderId,
  reviewerId,
  onClose,
  onOpened,
}: {
  orderId: string
  reviewerId: string
  onClose: () => void
  onOpened: () => void
}) {
  const [channel, setChannel] = useState<AppealRequest['channel']>('CUSTOMER_SUPPORT')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [reference, setReference] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const tooShort = note.trim().length < MIN_NOTE_CHARS

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      const event = await postAppeal(orderId, { channel, note: note.trim() }, reviewerId)
      const appeal = (event.payload as { appeal?: { appeal_reference?: string } }).appeal
      setReference(appeal?.appeal_reference ?? null)
      onOpened()
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.detail : 'The appeal could not be opened.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog title="Open an appeal" onClose={onClose}>
      {reference !== null ? (
        <div data-testid="appeal-opened">
          <p className="text-sm text-slate-100">
            Appeal opened. Reference <span className="font-mono">{reference}</span>.
          </p>
          <button
            type="button"
            onClick={onClose}
            className="mt-3 rounded border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 transition-colors duration-150 hover:bg-slate-700"
          >
            Done
          </button>
        </div>
      ) : (
        <form
          onSubmit={(event) => {
            event.preventDefault()
            if (!tooShort && !busy) void submit()
          }}
        >
          <label className="block text-xs text-slate-400">
            Channel
            <select
              data-testid="appeal-channel"
              value={channel}
              onChange={(event) => setChannel(event.target.value as AppealRequest['channel'])}
              className={FIELD}
            >
              <option value="CUSTOMER_SUPPORT">Customer support</option>
              <option value="EMAIL">Email</option>
            </select>
          </label>
          <label className="mt-3 block text-xs text-slate-400">
            Note
            <textarea
              data-testid="appeal-note"
              value={note}
              rows={3}
              onChange={(event) => setNote(event.target.value)}
              className={FIELD}
            />
          </label>
          <p className="mt-1 text-xs text-slate-500">
            {note.trim().length} characters · minimum {MIN_NOTE_CHARS}
          </p>
          {error && <p className="mt-2 text-xs text-slate-200">{error}</p>}
          <div className="mt-4 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded border border-slate-700 px-3 py-1.5 text-sm text-slate-300 transition-colors duration-150 hover:bg-slate-800"
            >
              Cancel
            </button>
            <button
              type="submit"
              data-testid="appeal-submit"
              disabled={tooShort || busy}
              className="rounded border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 transition-colors duration-150 hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Open appeal
            </button>
          </div>
        </form>
      )}
    </Dialog>
  )
}
