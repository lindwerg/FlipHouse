import { GIGAAM_AUTH_ERROR_PREFIX, GIGAAM_AUTH_FAIL_REASON } from '@fliphouse/shared';
import { expect, test, vi } from 'vitest';

import { MAX_PARK_CYCLES, probeGigaamHealth, runParkSweep } from './park-sweep.js';
import type { ParkSweepDeps, ParkValue } from './park-sweep.js';

const REQ = '11111111-1111-1111-1111-111111111111';
const PARK: ParkValue = {
  jobId: 'asr-job-1',
  contentHash: 'h',
  outputPrefix: 'intermediate/h/asr',
};
const RAW_KEY = 'intermediate/h/asr/_raw_gigaam.json';
const PAYLOAD = { duration: 1, language: 'ru', segments: [] };

function makeDeps(over: Partial<ParkSweepDeps> = {}): ParkSweepDeps {
  return {
    nowMs: () => 2_000_000,
    listExpired: vi.fn(async () => [REQ]),
    pollStatus: vi.fn(async () => ({ state: 'succeeded' as const, payload: PAYLOAD })),
    claim: vi.fn(async () => PARK),
    bumpDeadline: vi.fn(async () => 1),
    writeRaw: vi.fn(async () => {}),
    enqueueResume: vi.fn(async () => {}),
    enqueueFail: vi.fn(async () => {}),
    ...over,
  };
}

test('returns an empty summary when nothing is expired', async () => {
  const deps = makeDeps({ listExpired: vi.fn(async () => []) });

  const summary = await runParkSweep(deps);

  expect(summary).toEqual({ scanned: 0, resumed: 0, failed: 0, rearmed: 0, lostRace: 0 });
  expect(deps.pollStatus).not.toHaveBeenCalled();
});

test('a terminal success claims the key, writes the raw payload, and enqueues a resume', async () => {
  const deps = makeDeps();

  const summary = await runParkSweep(deps);

  expect(deps.pollStatus).toHaveBeenCalledWith(REQ);
  expect(deps.claim).toHaveBeenCalledWith(REQ);
  expect(deps.writeRaw).toHaveBeenCalledWith(RAW_KEY, PAYLOAD);
  expect(deps.enqueueResume).toHaveBeenCalledWith({
    jobId: 'asr-job-1',
    requestId: REQ,
    rawPayloadKey: RAW_KEY,
    contentHash: 'h',
    outputPrefix: 'intermediate/h/asr',
  });
  expect(summary).toMatchObject({ scanned: 1, resumed: 1, failed: 0 });
});

test('a terminal failure claims the key and enqueues an asr-fail', async () => {
  const deps = makeDeps({
    pollStatus: vi.fn(async () => ({ state: 'failed' as const, error: 'gpu died' })),
  });

  const summary = await runParkSweep(deps);

  expect(deps.enqueueFail).toHaveBeenCalledWith({ jobId: 'asr-job-1', error: 'gpu died' });
  expect(deps.writeRaw).not.toHaveBeenCalled();
  expect(summary).toMatchObject({ scanned: 1, failed: 1, resumed: 0 });
});

test('a lost-callback HF auth-class failure surfaces a DISTINCT diagnosable reason', async () => {
  // TRANS-4: an expired/terms-unaccepted HF_TOKEN must not masquerade as a generic
  // failure — the auth prefix maps to the operator-actionable reason.
  const deps = makeDeps({
    pollStatus: vi.fn(async () => ({
      state: 'failed' as const,
      error: `${GIGAAM_AUTH_ERROR_PREFIX} 403 access to model pyannote/segmentation-3.0 gated`,
    })),
  });

  await runParkSweep(deps);

  expect(deps.enqueueFail).toHaveBeenCalledWith({
    jobId: 'asr-job-1',
    error: expect.stringContaining(GIGAAM_AUTH_FAIL_REASON),
  });
});

test('a non-auth lost-callback failure passes its error through verbatim', async () => {
  const deps = makeDeps({
    pollStatus: vi.fn(async () => ({ state: 'failed' as const, error: 'cuda oom' })),
  });

  await runParkSweep(deps);

  expect(deps.enqueueFail).toHaveBeenCalledWith({ jobId: 'asr-job-1', error: 'cuda oom' });
});

test('probeGigaamHealth reports healthy on a 200', async () => {
  const result = await probeGigaamHealth({ fetchHealth: async () => ({ status: 200 }) });
  expect(result).toEqual({ healthy: true, status: 200 });
});

test('probeGigaamHealth reports an outage on a non-200', async () => {
  const result = await probeGigaamHealth({ fetchHealth: async () => ({ status: 503 }) });
  expect(result.healthy).toBe(false);
  expect(result.status).toBe(503);
  expect(result.reason).toMatch(/503/);
});

test('probeGigaamHealth reports a transport fault without throwing', async () => {
  const result = await probeGigaamHealth({
    fetchHealth: async () => {
      throw new Error('ECONNREFUSED');
    },
  });
  expect(result.healthy).toBe(false);
  expect(result.reason).toMatch(/unreachable/);
  expect(result.reason).toMatch(/ECONNREFUSED/);
});

test('probeGigaamHealth stringifies a non-Error rejection', async () => {
  const result = await probeGigaamHealth({
    fetchHealth: async () => {
      throw 'boom';
    },
  });
  expect(result.healthy).toBe(false);
  expect(result.reason).toMatch(/boom/);
});

test('a lost race (claim returns null) is counted and routed nowhere', async () => {
  const deps = makeDeps({ claim: vi.fn(async () => null) });

  const summary = await runParkSweep(deps);

  expect(deps.writeRaw).not.toHaveBeenCalled();
  expect(deps.enqueueResume).not.toHaveBeenCalled();
  expect(deps.enqueueFail).not.toHaveBeenCalled();
  expect(summary).toMatchObject({ scanned: 1, lostRace: 1 });
});

test('a still-processing prediction under the cycle cap re-arms its deadline (no claim)', async () => {
  const deps = makeDeps({
    pollStatus: vi.fn(async () => ({ state: 'processing' as const })),
    bumpDeadline: vi.fn(async () => MAX_PARK_CYCLES - 1),
  });

  const summary = await runParkSweep(deps);

  expect(deps.bumpDeadline).toHaveBeenCalledWith(REQ, expect.any(Number));
  expect(deps.claim).not.toHaveBeenCalled();
  expect(deps.enqueueFail).not.toHaveBeenCalled();
  expect(summary).toMatchObject({ scanned: 1, rearmed: 1 });
});

test('a still-processing prediction past the cycle cap claims and fails it (timeout)', async () => {
  const deps = makeDeps({
    pollStatus: vi.fn(async () => ({ state: 'processing' as const })),
    bumpDeadline: vi.fn(async () => MAX_PARK_CYCLES),
  });

  const summary = await runParkSweep(deps);

  expect(deps.claim).toHaveBeenCalledWith(REQ);
  expect(deps.enqueueFail).toHaveBeenCalledWith({
    jobId: 'asr-job-1',
    error: expect.stringMatching(/MAX_PARK_CYCLES|timed out|exceeded/i),
  });
  expect(summary).toMatchObject({ scanned: 1, failed: 1 });
});

test('a timeout that loses the claim race is counted as lostRace, not failed', async () => {
  const deps = makeDeps({
    pollStatus: vi.fn(async () => ({ state: 'processing' as const })),
    bumpDeadline: vi.fn(async () => MAX_PARK_CYCLES),
    claim: vi.fn(async () => null),
  });

  const summary = await runParkSweep(deps);

  expect(deps.enqueueFail).not.toHaveBeenCalled();
  expect(summary).toMatchObject({ scanned: 1, lostRace: 1, failed: 0 });
});

test('processes every expired request and aggregates the summary', async () => {
  const second = '22222222-2222-2222-2222-222222222222';
  const deps = makeDeps({
    listExpired: vi.fn(async () => [REQ, second]),
    pollStatus: vi
      .fn()
      .mockResolvedValueOnce({ state: 'succeeded', payload: PAYLOAD })
      .mockResolvedValueOnce({ state: 'failed', error: 'boom' }),
    claim: vi
      .fn()
      .mockResolvedValueOnce(PARK)
      .mockResolvedValueOnce({
        jobId: 'asr-job-2',
        contentHash: 'h2',
        outputPrefix: 'intermediate/h2/asr',
      }),
  });

  const summary = await runParkSweep(deps);

  expect(summary).toMatchObject({ scanned: 2, resumed: 1, failed: 1 });
});
