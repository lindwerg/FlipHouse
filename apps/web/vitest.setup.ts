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
