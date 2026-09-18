/**
 * The reviewer identity (§14.2: no auth platform, a placeholder header). The chosen id goes out as
 * `X-Reviewer-Id` on overrides and appeals and is remembered in localStorage, which can throw or return
 * nothing in a private window, so every access is guarded and the picker works without it.
 */
import { useCallback, useEffect, useState } from 'react'

export const REVIEWERS = ['reviewer-placeholder-01', 'reviewer-placeholder-02', 'reviewer-placeholder-03'] as const
export const STORAGE_KEY = 'sentinel.reviewer-id'

function readStored(): string | null {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY)
    return value !== null && (REVIEWERS as readonly string[]).includes(value) ? value : null
  } catch {
    return null
  }
}

function writeStored(value: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, value)
  } catch {
    /* private window, blocked site data: the picker still works for this session */
  }
}

export function useReviewerId(): [string, (value: string) => void] {
  const [reviewerId, setReviewerId] = useState<string>(() => readStored() ?? REVIEWERS[0])
  useEffect(() => {
    const stored = readStored()
    if (stored !== null && stored !== reviewerId) setReviewerId(stored)
    // Runs once: the stored value only changes through this hook.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const choose = useCallback((value: string) => {
    setReviewerId(value)
    writeStored(value)
  }, [])
  return [reviewerId, choose]
}

export function ReviewerPicker({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <label className="flex items-center gap-2 text-xs text-slate-400">
      <span>Reviewer</span>
      <select
        data-testid="reviewer-picker"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 transition-colors duration-150 hover:border-slate-600"
      >
        {REVIEWERS.map((reviewer) => (
          <option key={reviewer} value={reviewer}>
            {reviewer}
          </option>
        ))}
      </select>
    </label>
  )
}
