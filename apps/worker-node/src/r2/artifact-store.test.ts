import type { S3Client } from '@aws-sdk/client-s3';
import {
  CopyObjectCommand,
  GetObjectCommand,
  HeadObjectCommand,
  PutObjectCommand,
} from '@aws-sdk/client-s3';
import { expect, test, vi } from 'vitest';

import {
  R2ArtifactStore,
  SENTINEL_MAX_BYTES,
  SENTINEL_SCHEMA_VERSION,
  buildS3Config,
  isNotFound,
  isPreconditionFailed,
} from './artifact-store.js';

const SETTINGS = {
  accountId: 'acct123',
  accessKeyId: 'AK',
  secretAccessKey: 'SK',
};

/** AWS-SDK-shaped error: status on `$metadata`, code name on `name`. */
function awsError(httpStatusCode?: number, name?: string): Error {
  const err = new Error(name ?? `http ${httpStatusCode}`);
  if (name) err.name = name;
  Object.assign(err, { $metadata: { httpStatusCode } });
  return err;
}

/** A mock S3 client exposing only `send` (the single network seam). */
function mockClient(send: ReturnType<typeof vi.fn>): S3Client {
  return { send } as unknown as S3Client;
}

test('buildS3Config targets the R2 endpoint with WHEN_REQUIRED checksum knobs', () => {
  const config = buildS3Config(SETTINGS);
  expect(config.region).toBe('auto');
  expect(config.endpoint).toBe('https://acct123.r2.cloudflarestorage.com');
  expect(config.requestChecksumCalculation).toBe('WHEN_REQUIRED');
  expect(config.responseChecksumValidation).toBe('WHEN_REQUIRED');
});

test('isNotFound recognises a 404 status and a NotFound error name only', () => {
  expect(isNotFound(awsError(404))).toBe(true);
  expect(isNotFound(awsError(undefined, 'NotFound'))).toBe(true);
  expect(isNotFound(awsError(403))).toBe(false);
  expect(isNotFound(awsError(500))).toBe(false);
  expect(isNotFound(undefined)).toBe(false);
});

test('isPreconditionFailed recognises a 412 status and a PreconditionFailed name only', () => {
  expect(isPreconditionFailed(awsError(412))).toBe(true);
  expect(isPreconditionFailed(awsError(undefined, 'PreconditionFailed'))).toBe(true);
  expect(isPreconditionFailed(awsError(200))).toBe(false);
  expect(isPreconditionFailed(undefined)).toBe(false);
});

test('hasSentinel returns true when the _COMPLETE.json HEAD succeeds', async () => {
  const send = vi.fn().mockResolvedValue({});
  const store = new R2ArtifactStore({ bucket: 'b', s3Client: mockClient(send) });

  await expect(store.hasSentinel('intermediate/h/reframe')).resolves.toBe(true);

  const cmd = send.mock.calls[0]?.[0] as HeadObjectCommand;
  expect(cmd).toBeInstanceOf(HeadObjectCommand);
  expect(cmd.input).toMatchObject({ Bucket: 'b', Key: 'intermediate/h/reframe/_COMPLETE.json' });
});

test('hasSentinel returns false ONLY on a 404 (missing sentinel)', async () => {
  const send = vi.fn().mockRejectedValue(awsError(404));
  const store = new R2ArtifactStore({ bucket: 'b', s3Client: mockClient(send) });
  await expect(store.hasSentinel('p')).resolves.toBe(false);
});

test('hasSentinel rethrows a 403 — a broken-config error must never read as "not done"', async () => {
  const send = vi.fn().mockRejectedValue(awsError(403));
  const store = new R2ArtifactStore({ bucket: 'b', s3Client: mockClient(send) });
  await expect(store.hasSentinel('p')).rejects.toMatchObject({ $metadata: { httpStatusCode: 403 } });
});

test('writeSentinel PUTs _COMPLETE.json last with IfNoneMatch and an enriched body', async () => {
  const send = vi.fn().mockResolvedValue({});
  const store = new R2ArtifactStore({ bucket: 'b', s3Client: mockClient(send) });

  await store.writeSentinel('intermediate/h/reframe', { stage: 'reframe', contentHash: 'h' });

  const cmd = send.mock.calls[0]?.[0] as PutObjectCommand;
  expect(cmd).toBeInstanceOf(PutObjectCommand);
  expect(cmd.input).toMatchObject({
    Bucket: 'b',
    Key: 'intermediate/h/reframe/_COMPLETE.json',
    ContentType: 'application/json',
    IfNoneMatch: '*',
  });
  const body = JSON.parse(cmd.input.Body as string);
  expect(body).toMatchObject({ stage: 'reframe', contentHash: 'h', schemaVersion: SENTINEL_SCHEMA_VERSION });
  expect(typeof body.completedAt).toBe('string');
});

test('writeSentinel swallows a 412 (concurrent first-writer-wins) as an idempotent no-op', async () => {
  const send = vi.fn().mockRejectedValue(awsError(412));
  const store = new R2ArtifactStore({ bucket: 'b', s3Client: mockClient(send) });
  await expect(store.writeSentinel('p', {})).resolves.toBeUndefined();
});

test('writeSentinel swallows a 409 (delete+rewrite race) as an idempotent no-op', async () => {
  const send = vi.fn().mockRejectedValue(awsError(409));
  const store = new R2ArtifactStore({ bucket: 'b', s3Client: mockClient(send) });
  await expect(store.writeSentinel('p', {})).resolves.toBeUndefined();
});

test('writeSentinel rethrows a 500 (transient R2 error → BullMQ retry)', async () => {
  const send = vi.fn().mockRejectedValue(awsError(500));
  const store = new R2ArtifactStore({ bucket: 'b', s3Client: mockClient(send) });
  await expect(store.writeSentinel('p', {})).rejects.toMatchObject({ $metadata: { httpStatusCode: 500 } });
});

test('writeSentinel rejects an oversized marker before any network call', async () => {
  const send = vi.fn().mockResolvedValue({});
  const store = new R2ArtifactStore({ bucket: 'b', s3Client: mockClient(send) });
  const huge = { blob: 'x'.repeat(SENTINEL_MAX_BYTES + 1) };
  await expect(store.writeSentinel('p', huge)).rejects.toThrow(/SENTINEL_MAX_BYTES/);
  expect(send).not.toHaveBeenCalled();
});

test('hasFailedMarker returns true when the _FAILED.json HEAD succeeds', async () => {
  const send = vi.fn().mockResolvedValue({});
  const store = new R2ArtifactStore({ bucket: 'b', s3Client: mockClient(send) });

  await expect(store.hasFailedMarker('intermediate/h/asr')).resolves.toBe(true);

  const cmd = send.mock.calls[0]?.[0] as HeadObjectCommand;
  expect(cmd).toBeInstanceOf(HeadObjectCommand);
  expect(cmd.input).toMatchObject({ Bucket: 'b', Key: 'intermediate/h/asr/_FAILED.json' });
});

test('hasFailedMarker returns false on a 404 and rethrows other errors', async () => {
  const missing = new R2ArtifactStore({ bucket: 'b', s3Client: mockClient(vi.fn().mockRejectedValue(awsError(404))) });
  await expect(missing.hasFailedMarker('p')).resolves.toBe(false);

  const broken = new R2ArtifactStore({ bucket: 'b', s3Client: mockClient(vi.fn().mockRejectedValue(awsError(500))) });
  await expect(broken.hasFailedMarker('p')).rejects.toMatchObject({ $metadata: { httpStatusCode: 500 } });
});

test('writeFailedMarker PUTs _FAILED.json write-once with the error body', async () => {
  const send = vi.fn().mockResolvedValue({});
  const store = new R2ArtifactStore({ bucket: 'b', s3Client: mockClient(send) });

  await store.writeFailedMarker('intermediate/h/asr', 'gpu oom');

  const cmd = send.mock.calls[0]?.[0] as PutObjectCommand;
  expect(cmd).toBeInstanceOf(PutObjectCommand);
  expect(cmd.input).toMatchObject({
    Bucket: 'b',
    Key: 'intermediate/h/asr/_FAILED.json',
    ContentType: 'application/json',
    IfNoneMatch: '*',
  });
  const body = JSON.parse(cmd.input.Body as string);
  expect(body).toMatchObject({ error: 'gpu oom' });
  expect(typeof body.failedAt).toBe('string');
});

test('writeFailedMarker swallows a 412/409 (idempotent duplicate fail) and rethrows 500', async () => {
  const dup = new R2ArtifactStore({ bucket: 'b', s3Client: mockClient(vi.fn().mockRejectedValue(awsError(412))) });
  await expect(dup.writeFailedMarker('p', 'e')).resolves.toBeUndefined();

  const conflict = new R2ArtifactStore({ bucket: 'b', s3Client: mockClient(vi.fn().mockRejectedValue(awsError(409))) });
  await expect(conflict.writeFailedMarker('p', 'e')).resolves.toBeUndefined();

  const broken = new R2ArtifactStore({ bucket: 'b', s3Client: mockClient(vi.fn().mockRejectedValue(awsError(500))) });
  await expect(broken.writeFailedMarker('p', 'e')).rejects.toMatchObject({ $metadata: { httpStatusCode: 500 } });
});

test('readFailedError extracts the error string, falling back to "unknown"', async () => {
  const withError = new R2ArtifactStore({
    bucket: 'b',
    s3Client: mockClient(vi.fn().mockResolvedValue({ Body: { transformToString: async () => '{"error":"boom"}' } })),
  });
  await expect(withError.readFailedError('p')).resolves.toBe('boom');

  const noError = new R2ArtifactStore({
    bucket: 'b',
    s3Client: mockClient(vi.fn().mockResolvedValue({ Body: { transformToString: async () => '{"other":1}' } })),
  });
  await expect(noError.readFailedError('p')).resolves.toBe('unknown');
});

test('getJson fetches an object and parses its JSON body', async () => {
  const send = vi.fn().mockResolvedValue({ Body: { transformToString: async () => '{"schema_version":2}' } });
  const store = new R2ArtifactStore({ bucket: 'b', s3Client: mockClient(send) });

  await expect(store.getJson('intermediate/h/reframe/manifest.json')).resolves.toEqual({
    schema_version: 2,
  });

  const cmd = send.mock.calls[0]?.[0] as GetObjectCommand;
  expect(cmd).toBeInstanceOf(GetObjectCommand);
  expect(cmd.input).toMatchObject({ Bucket: 'b', Key: 'intermediate/h/reframe/manifest.json' });
});

test('getJson throws when the object response carries no body', async () => {
  const send = vi.fn().mockResolvedValue({});
  const store = new R2ArtifactStore({ bucket: 'b', s3Client: mockClient(send) });
  await expect(store.getJson('k')).rejects.toThrow(/no body/i);
});

test('copyObject server-side copies with a URL-encoded CopySource', async () => {
  const send = vi.fn().mockResolvedValue({});
  const store = new R2ArtifactStore({ bucket: 'b', s3Client: mockClient(send) });

  await store.copyObject('intermediate/h/reframe/clip_00.mp4', 'clips/h/clip_00.mp4');

  const cmd = send.mock.calls[0]?.[0] as CopyObjectCommand;
  expect(cmd).toBeInstanceOf(CopyObjectCommand);
  expect(cmd.input).toMatchObject({
    Bucket: 'b',
    CopySource: 'b/intermediate/h/reframe/clip_00.mp4',
    Key: 'clips/h/clip_00.mp4',
  });
});
