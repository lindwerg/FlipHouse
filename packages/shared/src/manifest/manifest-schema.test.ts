import { expect, test } from 'vitest';

import {
  ENGINE_NAME,
  MANIFEST_SCHEMA_VERSION,
  clipFileName,
  deriveClipKey,
  renderManifestSchema,
} from './manifest-schema.js';

const validClip = {
  rank: 0,
  score: 87.5,
  sub_scores: { hook: 9, emotion: 8, payoff: 9, visual: 7, audio: 8, pacing: 8 },
  confidence: 80,
  start_time: 12.0,
  end_time: 41.5,
  duration_s: 29.5,
  width: 1080,
  height: 1920,
  path: 'clip_000.mp4',
  title: 'Лучший момент',
  used_video: true,
  model_used: 'google/gemini-3.5-flash',
  modalities_used: ['text', 'video', 'audio'],
};

const validManifest = {
  schema_version: MANIFEST_SCHEMA_VERSION,
  source: 'uploads/a.mp4',
  engine: ENGINE_NAME,
  generated_at: '2026-06-17T00:00:00Z',
  resolution: [1080, 1920],
  clip_count: 1,
  clips: [validClip],
};

test('manifest constants match the Python contract', () => {
  expect(MANIFEST_SCHEMA_VERSION).toBe(1);
  expect(ENGINE_NAME).toBe('fliphouse-cpu-mediapipe-v1');
});

test('renderManifestSchema parses a well-formed manifest', () => {
  expect(renderManifestSchema.parse(validManifest)).toEqual(validManifest);
});

test('renderManifestSchema rejects a resolution that is not a [w,h] pair', () => {
  expect(renderManifestSchema.safeParse({ ...validManifest, resolution: [1080] }).success).toBe(false);
});

test('clipFileName zero-pads the rank to three digits', () => {
  expect(clipFileName(0)).toBe('clip_000.mp4');
  expect(clipFileName(12)).toBe('clip_012.mp4');
});

test('deriveClipKey builds a deterministic R2 key from hash and rank', () => {
  const hash = 'a'.repeat(64);
  expect(deriveClipKey(hash, 3)).toBe(`clips/${hash}/clip_003.mp4`);
  expect(deriveClipKey(hash, 3)).toBe(deriveClipKey(hash, 3));
});
