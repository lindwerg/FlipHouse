// Extends Vitest's `expect` with @testing-library/jest-dom matchers
// (toBeInTheDocument, toHaveAccessibleName, ...). Loaded for all projects via
// vitest.config.ts setupFiles; harmless for node-env tests that never touch the DOM.
import '@testing-library/jest-dom/vitest';
