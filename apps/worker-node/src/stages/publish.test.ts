import { expect, test, vi } from 'vitest';
import { ENGINE_NAME, MANIFEST_SCHEMA_VERSION, deriveClipKey } from '@fliphouse/shared';

import { publishUpload } from './publish.js';
import type { PublishDeps } from './publish.js';

const HASH = 'a'.repeat(64);

const MANIFEST = {
  schema_version: MANIFEST_SCHEMA_VERSION,
  source: 'uploads/a.mp4',
  engine: ENGINE_NAME,
  generated_at: '2026-06-17T00:00:00Z',
  resolution: [1080, 1920],
  clip_count: 2,
  clips: [
    {
      rank: 0,
      score: 88,
      sub_scores: { hook: 9 },
      confidence: 80,
      start_time: 1,
      end_time: 20,
      duration_s: 19,
      width: 1080,
      height: 1920,
      path: 'clip_000.mp4',
      title: 'A',
      used_video: true,
      model_used: 'gemini',
      modalities_used: ['text', 'video'],
    },
    {
      rank: 1,
      score: 70,
      sub_scores: { hook: 7 },
      confidence: 60,
      start_time: 30,
      end_time: 45,
      duration_s: 15,
      width: 1080,
      height: 1920,
      path: 'clip_001.mp4',
      title: 'B',
      used_video: false,
      model_used: 'gemini',
      modalities_used: ['text'],
    },
  ],
};

test('publishUpload parses the manifest, writes ranked clips, and finishes the upload', async () => {
  const upsertClips = vi.fn(async () => {});
  const finishUpload = vi.fn(async () => {});
  const deps: PublishDeps = {
    readJson: async () => MANIFEST,
    upsertClips,
    finishUpload,
  };

  const result = await publishUpload(
    { contentHash: HASH, manifestKey: `intermediate/${HASH}/store/manifest.json`, resultUrl: 'r' },
    deps,
  );

  expect(result.clipCount).toBe(2);

  const rows = upsertClips.mock.calls[0]?.[1] as ReadonlyArray<Record<string, unknown>>;
  expect(rows).toHaveLength(2);
  expect(rows[0]).toMatchObject({
    rank: 0,
    width: 1080,
    height: 1920,
    clipUrl: deriveClipKey(HASH, 0),
    score: '88',
    engine: ENGINE_NAME,
    manifestSchemaVersion: MANIFEST_SCHEMA_VERSION,
  });
  expect(finishUpload).toHaveBeenCalledWith(HASH, {
    resultUrl: 'r',
    manifestUrl: `intermediate/${HASH}/store/manifest.json`,
    engine: ENGINE_NAME,
  });
});

test('publishUpload rejects a malformed manifest', async () => {
  const deps: PublishDeps = {
    readJson: async () => ({ schema_version: 1, clips: 'nope' }),
    upsertClips: async () => {},
    finishUpload: async () => {},
  };

  await expect(
    publishUpload({ contentHash: HASH, manifestKey: 'm', resultUrl: 'r' }, deps),
  ).rejects.toThrow();
});
