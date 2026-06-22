import { ENGINE_NAME, MANIFEST_SCHEMA_VERSION, deriveClipKey } from '@fliphouse/shared';
import { expect, test, vi } from 'vitest';

import { publishUpload } from './publish.js';
import type { PublishDeps } from './publish.js';

const HASH = 'a'.repeat(64);
const CAPTION_PREFIX = `intermediate/${HASH}/caption`;
const DURABLE_MANIFEST = `clips/${HASH}/manifest.json`;

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

test('publishUpload promotes clips to the durable clips/ namespace and finishes the upload', async () => {
  const readJson = vi.fn(async () => MANIFEST);
  const copyObject = vi.fn(async () => {});
  const upsertClips = vi.fn(async () => {});
  const finishUpload = vi.fn(async () => {});
  const deps: PublishDeps = { readJson, copyObject, upsertClips, finishUpload };

  const result = await publishUpload({ contentHash: HASH, clipsPrefix: CAPTION_PREFIX }, deps);

  expect(result.clipCount).toBe(2);
  // The manifest is read from the caption prefix — no separate store artifact.
  expect(readJson).toHaveBeenCalledWith(`${CAPTION_PREFIX}/manifest.json`);

  // H9: each clip is server-side copied off the ephemeral intermediate/ prefix
  // into the durable clips/<hash>/ namespace; the manifest is promoted too.
  expect(copyObject).toHaveBeenCalledWith(`${CAPTION_PREFIX}/clip_00.mp4`, deriveClipKey(HASH, 0));
  expect(copyObject).toHaveBeenCalledWith(`${CAPTION_PREFIX}/clip_01.mp4`, deriveClipKey(HASH, 1));
  expect(copyObject).toHaveBeenCalledWith(`${CAPTION_PREFIX}/manifest.json`, DURABLE_MANIFEST);

  const rows = upsertClips.mock.calls[0]?.[1] as ReadonlyArray<Record<string, unknown>>;
  expect(rows).toHaveLength(2);
  expect(rows[0]).toMatchObject({
    rank: 0,
    width: 1080,
    height: 1920,
    // The clip URL is now the DURABLE key (reversed from the old intermediate-prefix
    // decision — intermediate/ is spec-deleted after 3 days, so URLs would 404).
    clipUrl: deriveClipKey(HASH, 0),
    score: '88',
    engine: ENGINE_NAME,
    manifestSchemaVersion: MANIFEST_SCHEMA_VERSION,
  });
  expect(rows[1]).toMatchObject({ rank: 1, clipUrl: deriveClipKey(HASH, 1) });

  // Delivered clips live in the durable clips/ namespace, never the ephemeral one.
  for (const row of rows) {
    expect(row.clipUrl as string).toContain(`clips/${HASH}/`);
    expect(row.clipUrl as string).not.toContain('intermediate/');
  }

  // Copy MUST precede the ledger write — a row must never point at a not-yet-copied object.
  expect(copyObject.mock.invocationCallOrder[0]).toBeLessThan(upsertClips.mock.invocationCallOrder[0]);

  expect(finishUpload).toHaveBeenCalledWith(HASH, {
    resultUrl: DURABLE_MANIFEST,
    manifestUrl: DURABLE_MANIFEST,
    engine: ENGINE_NAME,
  });
});

test('publishUpload rejects a malformed manifest (before any copy or write)', async () => {
  const copyObject = vi.fn(async () => {});
  const deps: PublishDeps = {
    readJson: async () => ({ schema_version: 2, clips: 'nope' }),
    copyObject,
    upsertClips: async () => {},
    finishUpload: async () => {},
  };

  await expect(
    publishUpload({ contentHash: HASH, clipsPrefix: CAPTION_PREFIX }, deps),
  ).rejects.toThrow();
  expect(copyObject).not.toHaveBeenCalled();
});
