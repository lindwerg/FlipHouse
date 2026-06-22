import { expect, test, vi } from 'vitest';

import { handlePostFinish } from './handle-post-finish.js';
import type { PostFinishDeps } from './handle-post-finish.js';

const HASH = 'a'.repeat(64);

function payload(meta: Record<string, string>) {
  return {
    Type: 'post-finish',
    Event: {
      Upload: {
        ID: 'tus_1',
        Size: 1024,
        MetaData: meta,
        Storage: { Bucket: 'uploads', Key: 'uploads/tus_1' },
      },
    },
  };
}

function makeDeps(claimed: boolean): {
  deps: PostFinishDeps;
  enqueue: ReturnType<typeof vi.fn>;
  markEnqueued: ReturnType<typeof vi.fn>;
} {
  const enqueue = vi.fn(async () => {});
  const markEnqueued = vi.fn(async () => {});
  const deps: PostFinishDeps = {
    claimUpload: async () =>
      claimed
        ? { claimed: true, existing: undefined }
        : {
            claimed: false,
            existing: {
              contentHash: HASH,
              ownerId: 'user_1',
              firstUploadId: 'tus_0',
              tusObjectKey: 'uploads/tus_0',
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
            },
          },
    enqueueFlow: enqueue,
    markEnqueued,
  };
  return { deps, enqueue, markEnqueued };
}

test('claims, enqueues, then marks the flow enqueued for a fresh upload', async () => {
  const { deps, enqueue, markEnqueued } = makeDeps(true);

  const outcome = await handlePostFinish(payload({ sha256: HASH, ownerId: 'user_1' }), deps);

  expect(outcome).toEqual({ kind: 'enqueued', contentHash: HASH });
  expect(enqueue).toHaveBeenCalledWith({ contentHash: HASH, ownerId: 'user_1', source: 'uploads/tus_1' });
  expect(markEnqueued).toHaveBeenCalledWith(HASH);
  // Marker MUST be written after the enqueue (crash-between → sweep re-enqueues idempotently).
  expect(enqueue.mock.invocationCallOrder[0]).toBeLessThan(markEnqueued.mock.invocationCallOrder[0]);
});

test('a re-delivered hook for an already-claimed upload is a no-op duplicate', async () => {
  const { deps, enqueue, markEnqueued } = makeDeps(false);

  const outcome = await handlePostFinish(payload({ sha256: HASH, ownerId: 'user_1' }), deps);

  expect(outcome.kind).toBe('duplicate');
  expect(enqueue).not.toHaveBeenCalled();
  expect(markEnqueued).not.toHaveBeenCalled();
});

test('an invalid/absent sha256 requires server-side hashing', async () => {
  const { deps } = makeDeps(true);

  const outcome = await handlePostFinish(payload({ ownerId: 'user_1' }), deps);

  expect(outcome).toEqual({ kind: 'hash-required', uploadId: 'tus_1' });
});

test('throws when ownerId metadata is missing', async () => {
  const { deps } = makeDeps(true);

  await expect(handlePostFinish(payload({ sha256: HASH }), deps)).rejects.toThrow(/missing ownerId/);
});

test('throws on a malformed (non post-finish) payload', async () => {
  const { deps } = makeDeps(true);

  await expect(handlePostFinish({ Type: 'pre-create' }, deps)).rejects.toThrow();
});
