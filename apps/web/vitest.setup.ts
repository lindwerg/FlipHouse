// Extends Vitest's `expect` with @testing-library/jest-dom matchers
// (toBeInTheDocument, toHaveAccessibleName, ...). Loaded for all projects via
// vitest.config.ts setupFiles; harmless for node-env tests that never touch the DOM.
import '@testing-library/jest-dom/vitest';

// jsdom does not implement window.matchMedia, which useReducedMotion relies on.
// Provide a default "motion allowed" (matches:false) stub; tests that exercise
// reduced motion override window.matchMedia themselves. Guarded for the node
// project where `window` is undefined.
if (typeof window !== 'undefined' && !window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList;
}

// jsdom does not implement ResizeObserver, which HeroAnimation uses to rescale
// the canvas to its container. Provide a no-op stub (same approach as the
// matchMedia stub above); the observer callback never needs to fire in unit
// tests — components just need construction not to throw. Guarded for the
// node project where `globalThis.ResizeObserver` is undefined.
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}
