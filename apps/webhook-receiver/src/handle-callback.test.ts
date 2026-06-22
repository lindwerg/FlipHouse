import { expect, test, vi } from 'vitest';

import { gpuCallbackSchema } from './gpu-callback-types.js';
import { handleCallback } from './handle-callback.js';
import type { CallbackDeps } from './handle-callback.js';

const SIG = 'sha256=deadbeef';

function makeDeps(overrides: Partial<CallbackDeps> = {}): {
  deps: CallbackDeps;
  resume: ReturnType<typeof vi.fn>;
  claim: ReturnType<typeof vi.fn>;
} {
  const resume = vi.fn(async () => {});
  const claim = vi.fn(async () => true);
  const deps: CallbackDeps = {
    verifyHmacFn: () => true,
    claimPrediction: claim,
    resumeParkedJob: resume,
    ...overrides,
  };
  return { deps, resume, claim };
}

function body(fields: Record<string, unknown>): string {
  return JSON.stringify(fields);
}

// gpu-callback-types contract (parsed before any mutation).

test('gpuCallbackSchema accepts a minimal succeeded payload', () => {
  expect(() => gpuCallbackSchema.parse({ id: 'pred_1', status: 'succeeded' })).not.toThrow();
});

test('gpuCallbackSchema rejects an unknown status', () => {
  expect(() => gpuCallbackSchema.parse({ id: 'pred_1', status: 'unknown' })).toThrow();
});

// handle-callback orchestration.

test('invalid HMAC short-circuits to hmac-invalid without resuming', async () => {
  const { deps, resume, claim } = makeDeps({ verifyHmacFn: () => false });

  const outcome = await handleCallback(body({ id: 'pred_1', status: 'succeeded' }), SIG, deps);

  expect(outcome.kind).toBe('hmac-invalid');
  expect(claim).not.toHaveBeenCalled();
  expect(resume).not.toHaveBeenCalled();
});

test('succeeded payload on first delivery resumes the parked job', async () => {
  const { deps, resume, claim } = makeDeps();

  const outcome = await handleCallback(
    body({ id: 'pred_1', status: 'succeeded', output: { url: 'r2://x' } }),
    SIG,
    deps,
  );

  expect(outcome).toEqual({ kind: 'verified-ok', predictionId: 'pred_1' });
  expect(claim).toHaveBeenCalledWith('pred_1');
  expect(resume).toHaveBeenCalledWith('pred_1', { ok: true, output: { url: 'r2://x' } });
});

test('a duplicate predictionId is a no-op that never resumes', async () => {
  const { deps, resume } = makeDeps({ claimPrediction: vi.fn(async () => false) });

  const outcome = await handleCallback(body({ id: 'pred_1', status: 'succeeded' }), SIG, deps);

  expect(outcome).toEqual({ kind: 'duplicate', predictionId: 'pred_1' });
  expect(resume).not.toHaveBeenCalled();
});

test('failed status resumes with a retryable failure envelope', async () => {
  const { deps, resume } = makeDeps();

  const outcome = await handleCallback(
    body({ id: 'pred_2', status: 'failed', error: 'OOM' }),
    SIG,
    deps,
  );

  expect(outcome).toEqual({ kind: 'verified-failed', predictionId: 'pred_2' });
  expect(resume).toHaveBeenCalledWith('pred_2', {
    ok: false,
    kind: 'retryable',
    error: 'OOM',
  });
});

test('canceled status maps to verified-failed', async () => {
  const { deps, resume } = makeDeps();

  const outcome = await handleCallback(body({ id: 'pred_3', status: 'canceled' }), SIG, deps);

  expect(outcome.kind).toBe('verified-failed');
  expect(resume).toHaveBeenCalledWith('pred_3', {
    ok: false,
    kind: 'retryable',
    error: 'canceled',
  });
});

test('malformed JSON after a passing HMAC throws (fail closed)', async () => {
  const { deps } = makeDeps();

  await expect(handleCallback('not json', SIG, deps)).rejects.toThrow();
});

test('a schema-invalid payload after a passing HMAC throws ZodError', async () => {
  const { deps } = makeDeps();

  await expect(
    handleCallback(body({ id: 'pred_1', status: 'unknown' }), SIG, deps),
  ).rejects.toThrow();
});
