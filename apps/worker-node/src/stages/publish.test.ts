import { expect, test, vi } from 'vitest';
import { ENGINE_NAME, MANIFEST_SCHEMA_VERSION } from '@fliphouse/shared';

import { publishUpload } from './publish.js';
import type { PublishDeps } from './publish.js';

const HASH = 'a'.repeat(64);
const REFRAME_PREFIX = `intermediate/${HASH}/reframe`;

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
      path: 'clip_00.mp4',
      title: 'A',
      used_video: true,
      model_used: 'gemini',
      modalities_used: ['text', 'video'],
      segment_count: 1,
      caption_band: null,
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
      path: 'clip_01.mp4',
      title: 'B',
      used_video: false,
      model_used: 'gemini',
      modalities_used: ['text'],
      segment_count: 1,
      caption_band: null,
    },
  ],
};

test('publishUpload reads the reframe manifest, writes ranked clips, and finishes the upload', async () => {
  const readJson = vi.fn(async () => MANIFEST);
  const upsertClips = vi.fn(async () => {});
  const finishUpload = vi.fn(async () => {});
  const deps: PublishDeps = { readJson, upsertClips, finishUpload };

  const result = await publishUpload({ contentHash: HASH, reframePrefix: REFRAME_PREFIX }, deps);

  expect(result.clipCount).toBe(2);
  // The manifest is read from the reframe prefix — no separate store artifact.
  expect(readJson).toHaveBeenCalledWith(`${REFRAME_PREFIX}/manifest.json`);

  const rows = upsertClips.mock.calls[0]?.[1] as ReadonlyArray<Record<string, unknown>>;
  expect(rows).toHaveLength(2);
  expect(rows[0]).toMatchObject({
    rank: 0,
    width: 1080,
    height: 1920,
    // The clip URL is the producer's actual R2 key (reframe prefix + bare path),
    // NOT a derived `clips/<hash>/...` key.
    clipUrl: `${REFRAME_PREFIX}/clip_00.mp4`,
    score: '88',
    engine: ENGINE_NAME,
    manifestSchemaVersion: MANIFEST_SCHEMA_VERSION,
  });
  expect(rows[1]).toMatchObject({ rank: 1, clipUrl: `${REFRAME_PREFIX}/clip_01.mp4` });

  // Guards the Fork-1 decision: clip keys must not regress to the old deriveClipKey path.
  for (const row of rows) {
    expect(row.clipUrl as string).not.toContain('clips/');
  }

  expect(finishUpload).toHaveBeenCalledWith(HASH, {
    resultUrl: `${REFRAME_PREFIX}/manifest.json`,
    manifestUrl: `${REFRAME_PREFIX}/manifest.json`,
    engine: ENGINE_NAME,
  });
});

test('publishUpload rejects a malformed manifest', async () => {
  const deps: PublishDeps = {
    readJson: async () => ({ schema_version: 2, clips: 'nope' }),
    upsertClips: async () => {},
    finishUpload: async () => {},
  };

  await expect(
    publishUpload({ contentHash: HASH, reframePrefix: REFRAME_PREFIX }, deps),
  ).rejects.toThrow();
});
