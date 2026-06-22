import { GetObjectCommand } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  CLIP_URL_TTL_SECONDS,
  buildR2PresignConfig,
  presignClipUrl,
  resolveR2Settings,
} from './r2-presign';

// getSignedUrl is the single AWS seam this module's logic depends on; mocking it
// lets us assert command shape + ttl without a live client or network. The live
// S3Client construction in r2-presign.ts is `v8 ignore`d (untestable glue).
vi.mock('@aws-sdk/s3-request-presigner', () => ({
  getSignedUrl: vi.fn(),
}));

const SIGNED = 'https://t3.storageapi.dev/test-clips/clips/abc/rank-1.mp4?X-Amz-Signature=deadbeef';

afterEach(() => {
  vi.mocked(getSignedUrl).mockReset();
});

describe('CLIP_URL_TTL_SECONDS', () => {
  it('is 6 hours in seconds', () => {
    expect(CLIP_URL_TTL_SECONDS).toBe(21600);
  });
});

describe('resolveR2Settings', () => {
  it('uses an explicit R2_ENDPOINT override when non-empty', () => {
    const settings = resolveR2Settings({
      R2_ENDPOINT: 'https://t3.storageapi.dev',
      R2_BUCKET: 'b',
      R2_ACCESS_KEY_ID: 'AK',
      R2_SECRET_ACCESS_KEY: 'SK',
    });
    expect(settings.endpoint).toBe('https://t3.storageapi.dev');
    expect(settings.bucket).toBe('b');
  });

  it('falls back to the Cloudflare R2 URL derived from R2_ACCOUNT_ID', () => {
    const settings = resolveR2Settings({
      R2_BUCKET: 'b',
      R2_ACCESS_KEY_ID: 'AK',
      R2_SECRET_ACCESS_KEY: 'SK',
      R2_ACCOUNT_ID: 'acct123',
    });
    expect(settings.accountId).toBe('acct123');
    expect(settings.endpoint).toBeUndefined();
  });

  it('throws naming R2_ACCOUNT_ID when neither endpoint nor account id is set', () => {
    expect(() =>
      resolveR2Settings({
        R2_BUCKET: 'b',
        R2_ACCESS_KEY_ID: 'AK',
        R2_SECRET_ACCESS_KEY: 'SK',
      }),
    ).toThrow(/R2_ACCOUNT_ID/);
  });

  it('treats an empty-string endpoint as absent (falls through to account id)', () => {
    const settings = resolveR2Settings({
      R2_ENDPOINT: '',
      R2_BUCKET: 'b',
      R2_ACCESS_KEY_ID: 'AK',
      R2_SECRET_ACCESS_KEY: 'SK',
      R2_ACCOUNT_ID: 'acct123',
    });
    expect(settings.endpoint).toBeUndefined();
    expect(settings.accountId).toBe('acct123');
  });
});

describe('buildR2PresignConfig', () => {
  it('targets the explicit endpoint with WHEN_REQUIRED checksum knobs', () => {
    const config = buildR2PresignConfig({
      endpoint: 'https://t3.storageapi.dev',
      bucket: 'b',
      accessKeyId: 'AK',
      secretAccessKey: 'SK',
    });
    expect(config.region).toBe('auto');
    expect(config.endpoint).toBe('https://t3.storageapi.dev');
    expect(config.requestChecksumCalculation).toBe('WHEN_REQUIRED');
    expect(config.responseChecksumValidation).toBe('WHEN_REQUIRED');
    expect(config.credentials).toEqual({ accessKeyId: 'AK', secretAccessKey: 'SK' });
  });

  it('derives the Cloudflare R2 endpoint from accountId when no override', () => {
    const config = buildR2PresignConfig({
      accountId: 'acct123',
      bucket: 'b',
      accessKeyId: 'AK',
      secretAccessKey: 'SK',
    });
    expect(config.endpoint).toBe('https://acct123.r2.cloudflarestorage.com');
  });
});

describe('presignClipUrl', () => {
  it('returns the presigned URL produced by getSignedUrl', async () => {
    vi.mocked(getSignedUrl).mockResolvedValue(SIGNED);

    const url = await presignClipUrl('clips/abc/rank-1.mp4');

    expect(url).toBe(SIGNED);
  });

  it('signs a GetObjectCommand for the right bucket + key with the 6h ttl', async () => {
    vi.mocked(getSignedUrl).mockResolvedValue(SIGNED);

    await presignClipUrl('clips/abc/rank-1.mp4');

    expect(getSignedUrl).toHaveBeenCalledTimes(1);
    const [, command, options] = vi.mocked(getSignedUrl).mock.calls[0]!;
    expect(command).toBeInstanceOf(GetObjectCommand);
    expect((command as GetObjectCommand).input).toEqual({
      Bucket: 'test-clips',
      Key: 'clips/abc/rank-1.mp4',
    });
    expect(options).toEqual({ expiresIn: CLIP_URL_TTL_SECONDS });
  });

  it('strips a leading slash from the key before signing', async () => {
    vi.mocked(getSignedUrl).mockResolvedValue(SIGNED);

    await presignClipUrl('/clips/abc/rank-1.mp4');

    const [, command] = vi.mocked(getSignedUrl).mock.calls[0]!;
    expect((command as GetObjectCommand).input.Key).toBe('clips/abc/rank-1.mp4');
  });
});
