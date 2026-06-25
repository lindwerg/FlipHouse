import type { StageRequest, StageResult } from '@fliphouse/shared';
import { expect, test, vi } from 'vitest';

import type { runPythonStage } from './spawn.js';
import { makeStageRunner } from './stage-runner.js';

const REQUEST: StageRequest = {
  version: 1,
  stage: 'score',
  contentHash: 'a'.repeat(64),
  ownerId: 'user_1',
  inputs: {},
  outputPrefix: 'intermediate/abc/score',
  params: {},
};

const OK: StageResult = { ok: true, outputs: [], metrics: {} };

test('makeStageRunner wires onStderrLine, forwarding each line tagged with stage + contentHash', async () => {
  // Arrange: a fake run that captures opts, then drives a stderr line through them.
  let captured: Parameters<typeof runPythonStage>[1];
  const fakeRun: typeof runPythonStage = (_req, opts) => {
    captured = opts;
    return Promise.resolve(OK);
  };
  const sink = vi.fn();
  const runStage = makeStageRunner(sink, fakeRun);

  // Act
  const result = await runStage(REQUEST);
  captured?.onStderrLine?.('A/V clip scored but model reported no video');

  // Assert: the result passes through, and the line reaches the sink with context.
  expect(result).toEqual(OK);
  expect(sink).toHaveBeenCalledWith('A/V clip scored but model reported no video', {
    stage: 'score',
    contentHash: 'a'.repeat(64),
  });
});

test('makeStageRunner forwards an abort signal to runPythonStage when given', async () => {
  let captured: Parameters<typeof runPythonStage>[1];
  const fakeRun: typeof runPythonStage = (_req, opts) => {
    captured = opts;
    return Promise.resolve(OK);
  };
  const controller = new AbortController();
  const runStage = makeStageRunner(() => undefined, fakeRun);

  await runStage(REQUEST, controller.signal);

  expect(captured?.signal).toBe(controller.signal);
});

test('makeStageRunner omits the signal key when none is supplied', async () => {
  let captured: Parameters<typeof runPythonStage>[1];
  const fakeRun: typeof runPythonStage = (_req, opts) => {
    captured = opts;
    return Promise.resolve(OK);
  };
  const runStage = makeStageRunner(() => undefined, fakeRun);

  await runStage(REQUEST);

  expect(captured && 'signal' in captured).toBe(false);
});
