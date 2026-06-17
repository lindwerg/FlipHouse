import { expect, test } from 'vitest';

import { resolvePythonEntry } from './resolve-entry.js';

test('defaults to the `python` interpreter and the CLI module', () => {
  const entry = resolvePythonEntry({});

  expect(entry.command).toBe('python');
  expect(entry.baseArgs).toEqual(['-m', 'fliphouse_worker.cli']);
});

test('honours FLIPHOUSE_PYTHON override', () => {
  const entry = resolvePythonEntry({ FLIPHOUSE_PYTHON: '/venv/bin/python' });

  expect(entry.command).toBe('/venv/bin/python');
});
