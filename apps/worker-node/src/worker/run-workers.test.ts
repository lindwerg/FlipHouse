import { expect, test } from 'vitest';

import { DEFAULT_SHUTDOWN_DEADLINE_MS, runPythonSelftest, shutdownDeadlineMs } from './run-workers.js';

test('shutdownDeadlineMs reads a positive override from env', () => {
  expect(shutdownDeadlineMs({ WORKER_SHUTDOWN_DEADLINE_MS: '12000' })).toBe(12000);
});

test('shutdownDeadlineMs falls back to the default for missing/invalid/non-positive values', () => {
  expect(shutdownDeadlineMs({})).toBe(DEFAULT_SHUTDOWN_DEADLINE_MS);
  expect(shutdownDeadlineMs({ WORKER_SHUTDOWN_DEADLINE_MS: 'abc' })).toBe(DEFAULT_SHUTDOWN_DEADLINE_MS);
  expect(shutdownDeadlineMs({ WORKER_SHUTDOWN_DEADLINE_MS: '0' })).toBe(DEFAULT_SHUTDOWN_DEADLINE_MS);
  expect(shutdownDeadlineMs({ WORKER_SHUTDOWN_DEADLINE_MS: '-5' })).toBe(DEFAULT_SHUTDOWN_DEADLINE_MS);
});

/**
 * Behavioural tests for the boot-time Python selftest gate. The real subprocess
 * spawn is a v8-ignored I/O seam; here we drive the pure exit-code → outcome
 * mapping through the injectable `_run` seam so the "fail fast on a broken
 * Python image" invariant (roadmap §2 node-python-failure) is verified without
 * touching a real interpreter.
 */

test('resolves when the Python selftest exits 0', async () => {
  // Arrange
  const calls: Array<{ command: string; args: readonly string[] }> = [];
  const run = async (command: string, args: readonly string[]): Promise<number> => {
    calls.push({ command, args });
    return 0;
  };

  // Act
  await runPythonSelftest({ FLIPHOUSE_PYTHON: '/venv/bin/python' }, { _run: run });

  // Assert: invoked the resolved interpreter with the CLI module + --selftest.
  expect(calls).toEqual([
    { command: '/venv/bin/python', args: ['-m', 'fliphouse_worker.cli', '--selftest'] },
  ]);
});

test('rejects with a "selftest failed" message when the subprocess exits non-zero', async () => {
  // Arrange
  const run = async (): Promise<number> => 1;

  // Act + Assert
  await expect(runPythonSelftest({}, { _run: run })).rejects.toThrow(/selftest failed/);
});

test('rejects when the subprocess cannot be spawned at all', async () => {
  // Arrange
  const run = async (): Promise<number> => {
    throw new Error('ENOENT: python not found');
  };

  // Act + Assert
  await expect(runPythonSelftest({}, { _run: run })).rejects.toThrow(/selftest failed/);
});
