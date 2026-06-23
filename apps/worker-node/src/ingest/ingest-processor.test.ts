import type { Job } from 'bullmq';
import { expect, test, vi } from 'vitest';

import type { IngestDeps } from './ingest-handler.js';
import { makeIngestProcessor } from './ingest-processor.js';
import { IngestDownloadError } from './ytdlp-download.js';

const HASH = 'b'.repeat(64);
const URL = 'https://youtu.be/abc';
const OWNER = 'user_1';

function job(data: unknown): Job {
  return { data } as unknown as Job;
}

function happyIngest(): IngestDeps {
  return {
    download: vi.fn().mockResolvedValue(undefined),
    hashFile: vi.fn().mockResolvedValue(HASH),
    putFile: vi.fn().mockResolvedValue(undefined),
    claimUpload: vi.fn().mockResolvedValue({ claimed: true, existing: undefined }),
    enqueueFlow: vi.fn().mockResolvedValue(undefined),
    markEnqueued: vi.fn().mockResolvedValue(undefined),
    tempPath: vi.fn().mockReturnValue('/tmp/x/source.mp4'),
    cleanup: vi.fn().mockResolvedValue(undefined),
  };
}

test('processor validates the payload and runs the ingest', async () => {
  const recordIngestFailure = vi.fn();
  const processor = makeIngestProcessor({ ingest: happyIngest(), recordIngestFailure });

  const result = await processor(job({ url: URL, ownerId: OWNER }), 'token', undefined as never);

  expect(result).toEqual({ kind: 'enqueued', contentHash: HASH });
  expect(recordIngestFailure).not.toHaveBeenCalled();
});

test('processor rejects a malformed payload at the schema boundary', async () => {
  const processor = makeIngestProcessor({ ingest: happyIngest(), recordIngestFailure: vi.fn() });

  await expect(
    processor(job({ url: 'not a url', ownerId: OWNER }), 'token', undefined as never),
  ).rejects.toBeInstanceOf(Error);
});

test('processor records a classified download failure durably, then rethrows', async () => {
  const recordIngestFailure = vi.fn().mockResolvedValue(undefined);
  const ingest = happyIngest();
  ingest.download = vi
    .fn()
    .mockRejectedValue(new IngestDownloadError('ip-blocked', 'YouTube заблокировал', 'sign in to confirm'));
  const processor = makeIngestProcessor({ ingest, recordIngestFailure });

  await expect(
    processor(job({ url: URL, ownerId: OWNER }), 'token', undefined as never),
  ).rejects.toBeInstanceOf(IngestDownloadError);
  expect(recordIngestFailure).toHaveBeenCalledWith(URL, OWNER, 'ip-blocked', 'YouTube заблокировал');
});

test('processor rethrows a non-download (infra) error WITHOUT recording an ingest failure', async () => {
  const recordIngestFailure = vi.fn();
  const ingest = happyIngest();
  ingest.putFile = vi.fn().mockRejectedValue(new Error('R2 down'));
  const processor = makeIngestProcessor({ ingest, recordIngestFailure });

  await expect(
    processor(job({ url: URL, ownerId: OWNER }), 'token', undefined as never),
  ).rejects.toThrow('R2 down');
  expect(recordIngestFailure).not.toHaveBeenCalled();
});
