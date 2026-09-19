/**
 * §A.5: no threshold, cost, guardrail number, policy version or model version is written into the frontend.
 * They come from the API.
 *
 * The scan reads every `.ts`/`.tsx` file under `src/` through Vite (no new dependency, no filesystem
 * access), minus the generated API types, the recorded fixtures and the tests themselves, and compares the
 * numeric literals it finds against every value in the recorded `GET /internal/policy` payload. Numbers
 * inside string and template literals are not numeric literals in this sense - a Tailwind class like
 * `duration-150` is not ₹150 - and the money test covers rendered strings separately. {0, 1, 2, 100} are
 * excluded as ordinary programming constants (a loop bound, a border width, a percentage denominator) that
 * happen to collide with a guardrail's signal count and a support cost; every rate, rupee amount and
 * probability threshold in the configuration is checked.
 */
import { describe, expect, it } from 'vitest'

import { POLICY } from './render'

const SKIP = /(?:^|\/)(?:__fixtures__|__tests__|test)\/|api\/types\.ts$/
const AMBIGUOUS = new Set([0, 1, 2, 100])

const MODULES = import.meta.glob('../**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as
  Record<string, string>

const SOURCES = Object.entries(MODULES)
  .filter(([path]) => !SKIP.test(path))
  .map(([path, text]) => [path.replace(/^\.\.\//, ''), text] as const)
  .sort(([a], [b]) => a.localeCompare(b))

/** Strip comments and string/template literals, so only code numbers remain. */
function code(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1 ')
    .replace(/'(?:\\.|[^'\\])*'/g, "''")
    .replace(/"(?:\\.|[^"\\])*"/g, '""')
    .replace(/`(?:\\.|[^`\\])*`/g, '``')
}

function numericLiterals(text: string): Set<number> {
  return new Set((code(text).match(/(?<![\w.$])\d+(?:\.\d+)?/g) ?? []).map(Number))
}

const POLICY_VALUES = POLICY.sections.flatMap((section) =>
  section.values.map((value) => value.value).filter((value): value is number => typeof value === 'number'),
)

describe('no policy value is hard-coded in the frontend', () => {
  it('has sources to scan and values to scan for', () => {
    expect(SOURCES.length).toBeGreaterThan(10)
    expect(POLICY_VALUES.length).toBeGreaterThan(10)
    expect(SOURCES.map(([path]) => path)).toContain('pages/OrderDetailPage.tsx')
    // Phase 10 §D: the "Try an order" panel and its form logic are scanned like every other source.
    expect(SOURCES.map(([path]) => path)).toEqual(expect.arrayContaining(['components/TryAnOrder.tsx', 'lib/tryOrder.ts']))
  })

  it.each(SOURCES)('%s contains no numeric literal equal to a policy config value', (_path, text) => {
    const literals = numericLiterals(text)
    expect(POLICY_VALUES.filter((value) => !AMBIGUOUS.has(value) && literals.has(value))).toEqual([])
  })

  it.each(SOURCES)('%s names no policy version and no model version', (_path, text) => {
    expect(text).not.toMatch(/v1\.0/)
    expect(text).not.toMatch(/(?:return|abuse)-hgb/)
    expect(text).not.toMatch(/fs-1\.0/)
  })
})
