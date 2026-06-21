import { readFileSync } from 'node:fs';

import { expect, test } from 'vitest';

import {
  ENGINE_NAME,
  MANIFEST_SCHEMA_VERSION,
  clipFileName,
  deriveClipKey,
  renderManifestSchema,
} from './manifest-schema.js';

/**
 * Real cross-language contract: this golden is a verbatim copy of the Python
 * `RenderManifest.to_dict()` byte-shape (tests/clipping/test_manifest.py). The
 * Python side asserts its live output still equals this file
 * (tests/clipping/test_golden_matches_shared.py), so any drift in EITHER
 * language fails CI instead of silently corrupting the dashboard.
 */
const golden = JSON.parse(
  readFileSync(new URL('./manifest-contract.golden.json', import.meta.url), 'utf8'),
) as Record<string, unknown>;

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
  path: 'clip_00.mp4',
  title: 'Лучший момент',
  used_video: true,
  model_used: 'google/gemini-3.5-flash',
  modalities_used: ['text', 'video', 'audio'],
  segment_count: 1,
  caption_band: null,
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

test('manifest constants match the Python golden (not a literal tautology)', () => {
  expect(MANIFEST_SCHEMA_VERSION).toBe(golden.schema_version);
  expect(ENGINE_NAME).toBe(golden.engine);
});

test('renderManifestSchema round-trips the Python golden byte-for-byte', () => {
  // A round-trip deep-equal catches a dropped field: if the zod schema strips a
  // key the Python side emits (segment_count / caption_band / a future field),
  // the parsed object no longer equals the golden and CI goes red.
  expect(renderManifestSchema.parse(golden)).toEqual(golden);
});

test('the golden clip path matches the canonical clipFileName', () => {
  const clips = golden.clips as Array<{ path: string }>;
  expect(clips[0]?.path).toBe(clipFileName(0));
});

test('renderManifestSchema parses a well-formed manifest', () => {
  expect(renderManifestSchema.parse(validManifest)).toEqual(validManifest);
});

test('renderManifestSchema rejects a resolution that is not a [w,h] pair', () => {
  expect(renderManifestSchema.safeParse({ ...validManifest, resolution: [1080] }).success).toBe(false);
});

test('a v1-shaped manifest (no segment_count / caption_band) still parses via defaults', () => {
  const { segment_count, caption_band, ...legacyClip } = validClip;
  const parsed = renderManifestSchema.parse({ ...validManifest, clips: [legacyClip] });
  expect(parsed.clips[0]?.segment_count).toBe(1);
  expect(parsed.clips[0]?.caption_band).toBeNull();
});

test('renderManifestSchema rejects a path-traversal clip path', () => {
  const evil = { ...validManifest, clips: [{ ...validClip, path: '../uploads/secret.mp4' }] };
  expect(renderManifestSchema.safeParse(evil).success).toBe(false);
});

test('clipFileName zero-pads the rank to two digits (matches Python clip_{rank:02d})', () => {
  expect(clipFileName(0)).toBe('clip_00.mp4');
  expect(clipFileName(12)).toBe('clip_12.mp4');
});

test('deriveClipKey builds a deterministic R2 key from hash and rank', () => {
  const hash = 'a'.repeat(64);
  expect(deriveClipKey(hash, 3)).toBe(`clips/${hash}/clip_03.mp4`);
  expect(deriveClipKey(hash, 3)).toBe(deriveClipKey(hash, 3));
});
