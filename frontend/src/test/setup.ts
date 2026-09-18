import '@testing-library/jest-dom/vitest'

/**
 * jsdom has no layout engine, so every element measures zero and nothing observes a resize. Recharts'
 * ResponsiveContainer and React Flow both refuse to draw without dimensions, so the shims below give the
 * document a fixed 1440x900 viewport and make ResizeObserver report it once per observed element. Nothing
 * here changes what a component computes; it only lets the components produce real DOM to assert against.
 */
const WIDTH = 1440
const HEIGHT = 900

class ResizeObserverStub {
  constructor(private readonly callback: ResizeObserverCallback) {}

  observe(target: Element) {
    const rect = { x: 0, y: 0, top: 0, left: 0, right: WIDTH, bottom: HEIGHT, width: WIDTH, height: HEIGHT }
    this.callback(
      [{ target, contentRect: rect, borderBoxSize: [], contentBoxSize: [], devicePixelContentBoxSize: [] }] as
        unknown as ResizeObserverEntry[],
      this as unknown as ResizeObserver,
    )
  }

  unobserve() {}
  disconnect() {}
}

class DOMMatrixStub {
  m22 = 1
}

globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver
globalThis.DOMMatrixReadOnly ??= DOMMatrixStub as unknown as typeof DOMMatrixReadOnly

Object.defineProperties(globalThis.HTMLElement.prototype, {
  offsetWidth: { get: () => WIDTH, configurable: true },
  offsetHeight: { get: () => HEIGHT, configurable: true },
  clientWidth: { get: () => WIDTH, configurable: true },
  clientHeight: { get: () => HEIGHT, configurable: true },
})

globalThis.Element.prototype.getBoundingClientRect = function getBoundingClientRect() {
  return {
    x: 0, y: 0, top: 0, left: 0, right: WIDTH, bottom: HEIGHT, width: WIDTH, height: HEIGHT,
    toJSON: () => ({}),
  } as DOMRect
}

globalThis.HTMLElement.prototype.scrollIntoView ??= () => {}
