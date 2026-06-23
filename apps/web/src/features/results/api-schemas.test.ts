import { describe, expect, it } from 'vitest';
import {
  clipsResponseSchema,
  clipViewSchema,
  contentHashParamSchema,
  ownerUploadSchema,
  progressResponseSchema,
  uploadsResponseSchema,
} from './api-schemas';

const HASH = 'a'.repeat(64);

const VALID_CLIP = {
  rank: 0,
  score: 87.5,
  startTime: 12,
  endTime: 41.5,
  durationS: 29.5,
  width: 1080,
  height: 1920,
  clipUrl: 'https://clips.example.com/clips/a/clip_00.mp4',
  title: 'best',
};

describe('contentHashParamSchema', () => {
  it('accepts a 64-char lowercase hex sha256', () => {
    expect(contentHashParamSchema.parse(HASH)).toBe(HASH);
  });

  it('rejects wrong length and uppercase/non-hex input', () => {
    expect(contentHashParamSchema.safeParse('abc').success).toBe(false);
    expect(contentHashParamSchema.safeParse('A'.repeat(64)).success).toBe(false);
    expect(contentHashParamSchema.safeParse(`${'g'.repeat(64)}`).success).toBe(false);
  });
});

describe('clipViewSchema', () => {
  it('accepts a fully-formed clip view', () => {
    expect(clipViewSchema.parse(VALID_CLIP)).toEqual(VALID_CLIP);
  });

  it('rejects a non-url clipUrl and a non-positive dimension', () => {
    expect(clipViewSchema.safeParse({ ...VALID_CLIP, clipUrl: 'not-a-url' }).success).toBe(false);
    expect(clipViewSchema.safeParse({ ...VALID_CLIP, width: 0 }).success).toBe(false);
  });
});

describe('clipsResponseSchema', () => {
  it('accepts a status with an array of clips', () => {
    const parsed = clipsResponseSchema.parse({ status: 'done', clips: [VALID_CLIP] });
    expect(parsed.clips).toHaveLength(1);
  });

  it('accepts an empty clip list and rejects an unknown status', () => {
    expect(clipsResponseSchema.parse({ status: 'queued', clips: [] }).clips).toEqual([]);
    expect(clipsResponseSchema.safeParse({ status: 'nope', clips: [] }).success).toBe(false);
  });
});

const VALID_UPLOAD = {
  contentHash: HASH,
  status: 'done',
  durationSec: 120,
  createdAt: '2026-01-01T00:00:00.000Z',
  clips: [VALID_CLIP],
};

describe('ownerUploadSchema', () => {
  it('accepts a done upload with a null duration and an in-flight one with no clips', () => {
    expect(ownerUploadSchema.parse(VALID_UPLOAD).clips).toHaveLength(1);
    expect(
      ownerUploadSchema.parse({ ...VALID_UPLOAD, durationSec: null, status: 'queued', clips: [] })
        .durationSec,
    ).toBeNull();
  });

  it('rejects a bad contentHash, an unknown status, and a non-iso createdAt', () => {
    expect(ownerUploadSchema.safeParse({ ...VALID_UPLOAD, contentHash: 'abc' }).success).toBe(false);
    expect(ownerUploadSchema.safeParse({ ...VALID_UPLOAD, status: 'nope' }).success).toBe(false);
    expect(ownerUploadSchema.safeParse({ ...VALID_UPLOAD, createdAt: 'yesterday' }).success).toBe(
      false,
    );
  });
});

describe('uploadsResponseSchema', () => {
  it('accepts an uploads array and an empty history', () => {
    expect(uploadsResponseSchema.parse({ uploads: [VALID_UPLOAD] }).uploads).toHaveLength(1);
    expect(uploadsResponseSchema.parse({ uploads: [] }).uploads).toEqual([]);
  });
});

describe('progressResponseSchema', () => {
  it('accepts a well-formed progress event', () => {
    expect(
      progressResponseSchema.parse({
        status: 'scoring',
        percent: 40,
        label: 'Оцениваем виральность',
        isTerminal: false,
      }).percent,
    ).toBe(40);
  });

  it('rejects an out-of-range percent', () => {
    expect(
      progressResponseSchema.safeParse({
        status: 'scoring',
        percent: 140,
        label: 'x',
        isTerminal: false,
      }).success,
    ).toBe(false);
  });
});
