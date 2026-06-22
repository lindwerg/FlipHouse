import { expect, test, vi } from 'vitest';

import {
  ASR_FAIL_JOB_NAME,
  ASR_RESUME_JOB_NAME,
  ENGINE_GIGAAM,
  resumeAsrProcessor,
} from './resume-asr.js';
import type { ResumeAsrDeps } from './resume-asr.js';

const HASH = 'a'.repeat(64);
const PREFIX = `intermediate/${HASH}/asr`;
const RAW_KEY = `${PREFIX}/_raw_gigaam.json`;

const RESUME_PAYLOAD = {
  jobId: 'asr-job-1',
  requestId: '11111111-1111-1111-1111-111111111111',
  rawPayloadKey: RAW_KEY,
  contentHash: HASH,
  outputPrefix: PREFIX,
};

function makeDeps(over: Partial<ResumeAsrDeps> = {}): ResumeAsrDeps {
  return {
    loadJob: vi.fn(async () => ({ changeDelay: vi.fn(async () => {}), outputPrefix: PREFIX })),
    runFinalize: vi.fn(async () => ({ ok: true as const, outputs: [], metrics: {} })),
    writeFailedMarker: vi.fn(async () => {}),
    ...over,
  };
}

function asrJob(name: string, data: unknown): { name: string; data: unknown } {
  return { name, data };
}

// ── asr-resume (success) ────────────────────────────────────────────────────

test('asr-resume spawns the finalize CLI then changeDelay(0) promotes the parked job', async () => {
  const changeDelay = vi.fn(async () => {});
  const loadJob = vi.fn(async () => ({ changeDelay, outputPrefix: PREFIX }));
  const runFinalize = vi.fn(async () => ({ ok: true as const, outputs: [], metrics: {} }));
  const deps = makeDeps({ loadJob, runFinalize });

  await resumeAsrProcessor(asrJob(ASR_RESUME_JOB_NAME, RESUME_PAYLOAD), deps);

  expect(runFinalize).toHaveBeenCalledWith({
    rawPayloadKey: RAW_KEY,
    outputPrefix: PREFIX,
    engine: ENGINE_GIGAAM,
  });
  // finalize BEFORE promotion: the `_COMPLETE` sentinel must exist before re-entry.
  expect(runFinalize.mock.invocationCallOrder[0]).toBeLessThan(changeDelay.mock.invocationCallOrder[0]);
  expect(loadJob).toHaveBeenCalledWith('asr-job-1');
  expect(changeDelay).toHaveBeenCalledWith(0);
});

test('asr-resume is a no-op promotion when the parked job is already gone', async () => {
  const runFinalize = vi.fn(async () => ({ ok: true as const, outputs: [], metrics: {} }));
  const deps = makeDeps({ loadJob: vi.fn(async () => undefined), runFinalize });

  // finalize still runs (idempotent, writes the sentinel) but there is nothing to promote.
  await expect(resumeAsrProcessor(asrJob(ASR_RESUME_JOB_NAME, RESUME_PAYLOAD), deps)).resolves.toBeUndefined();
  expect(runFinalize).toHaveBeenCalledOnce();
});

test('asr-resume surfaces a finalize failure (BullMQ retries the resume job)', async () => {
  const deps = makeDeps({
    runFinalize: vi.fn(async () => ({ ok: false as const, kind: 'retryable' as const, code: 'X', message: 'r2 down' })),
  });

  await expect(resumeAsrProcessor(asrJob(ASR_RESUME_JOB_NAME, RESUME_PAYLOAD), deps)).rejects.toThrow(/r2 down/);
});

test('asr-resume rejects a malformed resume payload at the boundary', async () => {
  const deps = makeDeps();
  await expect(resumeAsrProcessor(asrJob(ASR_RESUME_JOB_NAME, { jobId: 'x' }), deps)).rejects.toThrow();
});

// ── asr-fail (failure) ──────────────────────────────────────────────────────

test('asr-fail writes the _FAILED marker under the parked outputPrefix then promotes', async () => {
  const changeDelay = vi.fn(async () => {});
  const loadJob = vi.fn(async () => ({ changeDelay, outputPrefix: PREFIX }));
  const writeFailedMarker = vi.fn(async () => {});
  const deps = makeDeps({ loadJob, writeFailedMarker });

  await resumeAsrProcessor(asrJob(ASR_FAIL_JOB_NAME, { jobId: 'asr-job-1', error: 'gpu oom' }), deps);

  expect(writeFailedMarker).toHaveBeenCalledWith(PREFIX, 'gpu oom');
  expect(writeFailedMarker.mock.invocationCallOrder[0]).toBeLessThan(changeDelay.mock.invocationCallOrder[0]);
  expect(changeDelay).toHaveBeenCalledWith(0);
});

test('asr-fail is a no-op when the parked job is already gone (nothing to fail)', async () => {
  const writeFailedMarker = vi.fn(async () => {});
  const deps = makeDeps({ loadJob: vi.fn(async () => undefined), writeFailedMarker });

  await expect(
    resumeAsrProcessor(asrJob(ASR_FAIL_JOB_NAME, { jobId: 'gone', error: 'e' }), deps),
  ).resolves.toBeUndefined();
  expect(writeFailedMarker).not.toHaveBeenCalled();
});

test('asr-fail rejects a malformed fail payload at the boundary', async () => {
  const deps = makeDeps();
  await expect(resumeAsrProcessor(asrJob(ASR_FAIL_JOB_NAME, { jobId: 'x' }), deps)).rejects.toThrow();
});

// ── unknown job name ────────────────────────────────────────────────────────

test('rejects an unknown job name on the asr-resume queue', async () => {
  const deps = makeDeps();
  await expect(resumeAsrProcessor(asrJob('asr-other', RESUME_PAYLOAD), deps)).rejects.toThrow(/unknown.*job name/i);
});
