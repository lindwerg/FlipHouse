import type { ClaimResult, UploadRow } from '@fliphouse/db';
import { expect, test, vi } from 'vitest';

import { ingestFlowJobId, runIngest, sourceKey } from './ingest-handler.js';
import type { IngestDeps } from './ingest-handler.js';

const HASH = 'a'.repeat(64);
const URL = 'https://youtu.be/abc';
const OWNER = 'user_1';
const TEMP = '/tmp/fh-ingest/source.mp4';

/** A fresh set of injected deps with sensible happy-path defaults + spies. */
function makeDeps(overrides: Partial<IngestDeps> = {}): IngestDeps & {
  download: ReturnType<typeof vi.fn>;
  putFile: ReturnType<typeof vi.fn>;
  claimUpload: ReturnType<typeof vi.fn>;
  enqueueFlow: ReturnType<typeof vi.fn>;
  markEnqueued: ReturnType<typeof vi.fn>;
  cleanup: ReturnType<typeof vi.fn>;
} {
  const claimed: ClaimResult = { claimed: true, existing: undefined };
  const base = {
    download: vi.fn().mockResolvedValue(undefined),
    hashFile: vi.fn().mockResolvedValue(HASH),
    putFile: vi.fn().mockResolvedValue(undefined),
    claimUpload: vi.fn().mockResolvedValue(claimed),
    enqueueFlow: vi.fn().mockResolvedValue(undefined),
    markEnqueued: vi.fn().mockResolvedValue(undefined),
    tempPath: vi.fn().mockReturnValue(TEMP),
    cleanup: vi.fn().mockResolvedValue(undefined),
  };
  return { ...base, ...overrides } as never;
}

test('sourceKey is the content-addressed sources/<hash>.mp4 key', () => {
  expect(sourceKey(HASH)).toBe(`sources/${HASH}.mp4`);
});

test('ingestFlowJobId is the canonical content-derived flow root jobId', () => {
  expect(ingestFlowJobId(HASH)).toBe(`flow-${HASH}`);
});

test('runIngest downloads, hashes, uploads to R2, claims, enqueues, and marks enqueued', async () => {
  const deps = makeDeps();

  const outcome = await runIngest({ url: URL, ownerId: OWNER }, deps);

  expect(outcome).toEqual({ kind: 'enqueued', contentHash: HASH });
  expect(deps.download).toHaveBeenCalledWith(URL, TEMP);
  expect(deps.putFile).toHaveBeenCalledWith(TEMP, `sources/${HASH}.mp4`, 'video/mp4');
  expect(deps.claimUpload).toHaveBeenCalledWith({
    contentHash: HASH,
    ownerId: OWNER,
    firstUploadId: `ingest:${HASH}`,
    tusObjectKey: `sources/${HASH}.mp4`,
  });
  expect(deps.enqueueFlow).toHaveBeenCalledWith({
    contentHash: HASH,
    ownerId: OWNER,
    source: `sources/${HASH}.mp4`,
  });
  expect(deps.markEnqueued).toHaveBeenCalledWith(HASH);
  expect(deps.cleanup).toHaveBeenCalledWith(TEMP);
});

test('runIngest treats a lost claim (duplicate content) as a no-op, never re-enqueuing', async () => {
  const existing = { contentHash: HASH, ownerId: OWNER } as unknown as UploadRow;
  const deps = makeDeps({
    claimUpload: vi.fn().mockResolvedValue({ claimed: false, existing }),
  });

  const outcome = await runIngest({ url: URL, ownerId: OWNER }, deps);

  expect(outcome).toEqual({ kind: 'duplicate', contentHash: HASH, existing });
  expect(deps.enqueueFlow).not.toHaveBeenCalled();
  expect(deps.markEnqueued).not.toHaveBeenCalled();
  // The temp file is still cleaned up on the duplicate path.
  expect(deps.cleanup).toHaveBeenCalledWith(TEMP);
});

test('runIngest rejects a produced hash that is not a valid content hash (no claim)', async () => {
  const deps = makeDeps({ hashFile: vi.fn().mockResolvedValue('not-a-valid-hash') });

  await expect(runIngest({ url: URL, ownerId: OWNER }, deps)).rejects.toThrow(/invalid content hash/);
  expect(deps.putFile).not.toHaveBeenCalled();
  expect(deps.claimUpload).not.toHaveBeenCalled();
  // Cleanup still runs (finally guard).
  expect(deps.cleanup).toHaveBeenCalledWith(TEMP);
});

test('runIngest always cleans up the temp file even when the download throws', async () => {
  const deps = makeDeps({ download: vi.fn().mockRejectedValue(new Error('boom')) });

  await expect(runIngest({ url: URL, ownerId: OWNER }, deps)).rejects.toThrow('boom');
  expect(deps.hashFile).not.toHaveBeenCalled();
  expect(deps.cleanup).toHaveBeenCalledWith(TEMP);
});
