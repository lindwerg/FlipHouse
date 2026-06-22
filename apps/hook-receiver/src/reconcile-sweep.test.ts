import type { UploadRow } from '@fliphouse/db';
import { expect, test, vi } from 'vitest';


import { sweepStuckFlows } from './reconcile-sweep.js';
import type { SweepDeps } from './reconcile-sweep.js';

const GRACE_MS = 5 * 60_000;

function row(contentHash: string): UploadRow {
  return {
    contentHash,
    ownerId: 'user_1',
    firstUploadId: 'tus_0',
    tusObjectKey: `uploads/${contentHash}`,
    status: 'scoring',
    flowJobId: null,
    sizeBytes: 1,
    durationSec: null,
    resultUrl: null,
    manifestUrl: null,
    engine: null,
    error: null,
    attempts: 0,
    createdAt: new Date(),
    updatedAt: new Date(),
  };
}

test('no stuck rows → returns 0 and never enqueues', async () => {
  const enqueue = vi.fn(async () => {});
  const deps: SweepDeps = { findStuck: async () => [], enqueue };

  const count = await sweepStuckFlows(deps, GRACE_MS);

  expect(count).toBe(0);
  expect(enqueue).not.toHaveBeenCalled();
});

test('two stuck rows → re-enqueues both with mapped EnqueueArgs, returns 2', async () => {
  const enqueue = vi.fn(async () => {});
  const deps: SweepDeps = { findStuck: async () => [row('a'.repeat(64)), row('b'.repeat(64))], enqueue };

  const count = await sweepStuckFlows(deps, GRACE_MS);

  expect(count).toBe(2);
  expect(enqueue).toHaveBeenCalledTimes(2);
  expect(enqueue).toHaveBeenCalledWith({
    contentHash: 'a'.repeat(64),
    ownerId: 'user_1',
    source: `uploads/${'a'.repeat(64)}`,
  });
});

test('enqueue throwing on one row → sweep continues the rest and returns the success count', async () => {
  const enqueue = vi
    .fn<(args: unknown) => Promise<void>>()
    .mockRejectedValueOnce(new Error('redis down'))
    .mockResolvedValueOnce(undefined);
  const deps: SweepDeps = { findStuck: async () => [row('a'.repeat(64)), row('b'.repeat(64))], enqueue };

  const count = await sweepStuckFlows(deps, GRACE_MS);

  expect(count).toBe(1);
  expect(enqueue).toHaveBeenCalledTimes(2);
});

test('olderThan cutoff is now minus the grace TTL (a strictly past instant)', async () => {
  let captured: Date | undefined;
  const before = Date.now() - GRACE_MS;
  const deps: SweepDeps = {
    findStuck: async (olderThan) => {
      captured = olderThan;
      return [];
    },
    enqueue: async () => {},
  };

  await sweepStuckFlows(deps, GRACE_MS);
  const after = Date.now() - GRACE_MS;

  expect(captured).toBeInstanceOf(Date);
  expect(captured!.getTime()).toBeGreaterThanOrEqual(before);
  expect(captured!.getTime()).toBeLessThanOrEqual(after);
  expect(captured!.getTime()).toBeLessThan(Date.now());
});
