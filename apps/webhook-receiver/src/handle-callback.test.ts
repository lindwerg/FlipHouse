import { GIGAAM_AUTH_ERROR_PREFIX, GIGAAM_AUTH_FAIL_REASON } from '@fliphouse/shared';
import { expect, test, vi } from 'vitest';

import {
  handleCallback,
  parkKeyFor,
  PARK_KEY_PREFIX,
  parkValueSchema,
  QUEUE_ASR_RESUME,
  rawPayloadKeyFor,
} from './handle-callback.js';
import type { CallbackDeps, ParkValue } from './handle-callback.js';

const SIG = 'sha256=deadbeef';
const TS = '1700000000';
const REQUEST_ID = '11111111-2222-4333-8444-555555555555';

const PARK_VALUE: ParkValue = {
  jobId: 'asr-job-1',
  contentHash: 'hashabc',
  outputPrefix: 'intermediate/hashabc/asr',
};

function makeDeps(overrides: Partial<CallbackDeps> = {}): {
  deps: CallbackDeps;
  claim: ReturnType<typeof vi.fn>;
  writeRaw: ReturnType<typeof vi.fn>;
  enqueue: ReturnType<typeof vi.fn>;
  fail: ReturnType<typeof vi.fn>;
} {
  const claim = vi.fn(async (): Promise<ParkValue | null> => PARK_VALUE);
  const writeRaw = vi.fn(async () => {});
  const enqueue = vi.fn(async () => {});
  const fail = vi.fn(async () => {});
  const deps: CallbackDeps = {
    verifyHmacFn: () => true,
    claimPrediction: claim,
    writeRawPayload: writeRaw,
    enqueueResume: enqueue,
    failParkedJob: fail,
    ...overrides,
  };
  return { deps, claim, writeRaw, enqueue, fail };
}

function succeededBody(): string {
  return JSON.stringify({
    request_id: REQUEST_ID,
    status: 'succeeded',
    engine: 'gigaam-v3',
    payload: {
      duration: 5,
      language: 'ru',
      segments: [{ start: 0, end: 1, words: [{ word: 'да', start: 0, end: 0.4 }] }],
    },
  });
}

function failedBody(error: string): string {
  return JSON.stringify({ request_id: REQUEST_ID, status: 'failed', error });
}

// constants + key helpers

test('parkKeyFor composes the park key with the documented prefix', () => {
  expect(parkKeyFor(REQUEST_ID)).toBe(`${PARK_KEY_PREFIX}${REQUEST_ID}`);
});

test('rawPayloadKeyFor uses the contract R2 layout', () => {
  expect(rawPayloadKeyFor('hashabc')).toBe('intermediate/hashabc/asr/_raw_gigaam.json');
});

test('QUEUE_ASR_RESUME is the contract queue name', () => {
  expect(QUEUE_ASR_RESUME).toBe('asr-resume');
});

test('parkValueSchema validates the documented shape', () => {
  expect(parkValueSchema.parse(PARK_VALUE)).toEqual(PARK_VALUE);
  expect(() => parkValueSchema.parse({ jobId: 'x' })).toThrow();
});

// orchestration

test('invalid HMAC short-circuits to hmac-invalid without claiming', async () => {
  const { deps, claim } = makeDeps({ verifyHmacFn: () => false });

  const outcome = await handleCallback(succeededBody(), SIG, TS, deps);

  expect(outcome).toEqual({ kind: 'hmac-invalid' });
  expect(claim).not.toHaveBeenCalled();
});

test('verifyHmacFn receives the raw body, signature, and timestamp', async () => {
  const verify = vi.fn(() => true);
  const { deps } = makeDeps({ verifyHmacFn: verify });

  await handleCallback(succeededBody(), SIG, TS, deps);

  expect(verify).toHaveBeenCalledWith(succeededBody(), SIG, TS);
});

test('a winning succeeded claim writes raw payload to R2 then enqueues asr-resume', async () => {
  const { deps, claim, writeRaw, enqueue, fail } = makeDeps();

  const outcome = await handleCallback(succeededBody(), SIG, TS, deps);

  expect(outcome).toEqual({ kind: 'verified-ok', requestId: REQUEST_ID });
  expect(claim).toHaveBeenCalledWith(REQUEST_ID);
  expect(writeRaw).toHaveBeenCalledWith('intermediate/hashabc/asr/_raw_gigaam.json', {
    duration: 5,
    language: 'ru',
    segments: [{ start: 0, end: 1, words: [{ word: 'да', start: 0, end: 0.4 }] }],
  });
  expect(enqueue).toHaveBeenCalledWith({
    jobId: 'asr-job-1',
    requestId: REQUEST_ID,
    rawPayloadKey: 'intermediate/hashabc/asr/_raw_gigaam.json',
    contentHash: 'hashabc',
    outputPrefix: 'intermediate/hashabc/asr',
  });
  expect(fail).not.toHaveBeenCalled();
});

test('the R2 write happens before the enqueue (no orphaned job without its payload)', async () => {
  const order: string[] = [];
  const { deps } = makeDeps({
    writeRawPayload: vi.fn(async () => {
      order.push('write');
    }),
    enqueueResume: vi.fn(async () => {
      order.push('enqueue');
    }),
  });

  await handleCallback(succeededBody(), SIG, TS, deps);

  expect(order).toEqual(['write', 'enqueue']);
});

test('a duplicate/late callback (null claim) is a no-op', async () => {
  const { deps, writeRaw, enqueue, fail } = makeDeps({
    claimPrediction: vi.fn(async () => null),
  });

  const outcome = await handleCallback(succeededBody(), SIG, TS, deps);

  expect(outcome).toEqual({ kind: 'duplicate', requestId: REQUEST_ID });
  expect(writeRaw).not.toHaveBeenCalled();
  expect(enqueue).not.toHaveBeenCalled();
  expect(fail).not.toHaveBeenCalled();
});

test('a winning failed claim fails the parked job with the provider error', async () => {
  const { deps, writeRaw, enqueue, fail } = makeDeps();

  const outcome = await handleCallback(failedBody('gpu OOM'), SIG, TS, deps);

  expect(outcome).toEqual({ kind: 'verified-failed', requestId: REQUEST_ID });
  expect(fail).toHaveBeenCalledWith('asr-job-1', 'gpu OOM');
  expect(writeRaw).not.toHaveBeenCalled();
  expect(enqueue).not.toHaveBeenCalled();
});

test('an HF auth-class failed callback maps to a distinct diagnosable fail reason', async () => {
  // TRANS-4: an expired/terms-unaccepted HF_TOKEN (auth prefix) must surface a
  // distinct operator-actionable reason, not an indistinguishable "failed".
  const { deps, fail } = makeDeps();

  const outcome = await handleCallback(
    failedBody(`${GIGAAM_AUTH_ERROR_PREFIX} 403 access to model pyannote/segmentation-3.0 gated`),
    SIG,
    TS,
    deps,
  );

  expect(outcome).toEqual({ kind: 'verified-failed', requestId: REQUEST_ID });
  expect(fail).toHaveBeenCalledWith('asr-job-1', expect.stringContaining(GIGAAM_AUTH_FAIL_REASON));
});

test('a failed callback that loses the claim never fails the job', async () => {
  const { deps, fail } = makeDeps({ claimPrediction: vi.fn(async () => null) });

  const outcome = await handleCallback(failedBody('gpu OOM'), SIG, TS, deps);

  expect(outcome).toEqual({ kind: 'duplicate', requestId: REQUEST_ID });
  expect(fail).not.toHaveBeenCalled();
});

test('malformed JSON after a passing HMAC throws (fail closed)', async () => {
  const { deps } = makeDeps();

  await expect(handleCallback('not json', SIG, TS, deps)).rejects.toThrow();
});

test('a schema-invalid payload after a passing HMAC throws ZodError', async () => {
  const { deps } = makeDeps();

  await expect(
    handleCallback(JSON.stringify({ request_id: REQUEST_ID, status: 'unknown' }), SIG, TS, deps),
  ).rejects.toThrow();
});
