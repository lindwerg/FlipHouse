import { ENGINE_NAME, MANIFEST_SCHEMA_VERSION, deriveClipKey } from '@fliphouse/shared';
import { expect, test, vi } from 'vitest';

import { publishUpload } from './publish.js';
import type { PublishDeps } from './publish.js';

const HASH = 'a'.repeat(64);
const CAPTION_PREFIX = `intermediate/${HASH}/caption`;
const DURABLE_MANIFEST = `clips/${HASH}/manifest.json`;
const OWNER = 'user_1';

/** PublishDeps with vi.fn billing seams that load a 120s upload owned by OWNER. */
function billingDeps(
  over: Partial<PublishDeps> = {},
): { deps: PublishDeps; debitPayg: ReturnType<typeof vi.fn>; recordCogs: ReturnType<typeof vi.fn> } {
  const debitPayg = vi.fn(async () => true);
  const recordCogs = vi.fn(async () => {});
  const deps: PublishDeps = {
    readJson: async () => MANIFEST,
    copyObject: async () => {},
    upsertClips: async () => {},
    finishUpload: async () => {},
    loadUpload: async () => ({ ownerId: OWNER, durationSec: 120 }),
    debitPayg,
    recordCogs,
    ...over,
  };
  return { deps, debitPayg, recordCogs };
}

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
  const { deps } = billingDeps({ readJson, copyObject, upsertClips, finishUpload });

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
  const { deps, debitPayg } = billingDeps({
    readJson: async () => ({ schema_version: 2, clips: 'nope' }),
    copyObject,
  });

  await expect(
    publishUpload({ contentHash: HASH, clipsPrefix: CAPTION_PREFIX }, deps),
  ).rejects.toThrow();
  expect(copyObject).not.toHaveBeenCalled();
  // A malformed manifest never reaches terminal success → NO charge.
  expect(debitPayg).not.toHaveBeenCalled();
});

test('charges PAYG keyed on (owner, contentHash) and records COGS — AFTER finishUpload', async () => {
  const finishUpload = vi.fn(async () => {});
  const { deps, debitPayg, recordCogs } = billingDeps({ finishUpload });

  await publishUpload({ contentHash: HASH, clipsPrefix: CAPTION_PREFIX }, deps);

  // 120s source → exactly 2 minutes → $0.50 = 500_000 micro-USDT.
  expect(debitPayg).toHaveBeenCalledWith({ userId: OWNER, jobId: HASH, amountMicros: 500_000n });
  expect(recordCogs).toHaveBeenCalledWith({
    contentHash: HASH,
    ownerId: OWNER,
    costUsdMicros: 0n, // documented follow-up: real cost threads through the manifest later
    engine: ENGINE_NAME,
  });
  // Charge fires strictly AFTER the upload is durably finished.
  expect(finishUpload.mock.invocationCallOrder[0]).toBeLessThan(
    debitPayg.mock.invocationCallOrder[0],
  );
});

test.each([
  [1, 250_000n], // 1s → 1-minute minimum → $0.25
  [60, 250_000n], // exactly 1 minute → $0.25
  [61, 500_000n], // just over → 2 minutes → $0.50
  [null, 250_000n], // missing probe → floor to the 1-minute minimum (never free)
])('charges the rounded PAYG amount for a %ss source', async (durationSec, expectedMicros) => {
  const { deps, debitPayg } = billingDeps({
    loadUpload: async () => ({ ownerId: OWNER, durationSec }),
  });

  await publishUpload({ contentHash: HASH, clipsPrefix: CAPTION_PREFIX }, deps);

  expect(debitPayg).toHaveBeenCalledWith({ userId: OWNER, jobId: HASH, amountMicros: expectedMicros });
});

test('a duplicate re-publish does not double-charge (debitPayg returns false → no-op)', async () => {
  // The ledger's ON CONFLICT makes the second debit a no-op; publish still calls
  // it idempotently and tolerates the `false` (already-charged) result.
  const debitPayg = vi.fn(async () => false);
  const { deps } = billingDeps({ debitPayg });

  const result = await publishUpload({ contentHash: HASH, clipsPrefix: CAPTION_PREFIX }, deps);

  expect(result.clipCount).toBe(2);
  expect(debitPayg).toHaveBeenCalledOnce();
});

test('skips billing when the ledger row vanished (loadUpload → null) rather than guessing an owner', async () => {
  const { deps, debitPayg, recordCogs } = billingDeps({ loadUpload: async () => null });

  await publishUpload({ contentHash: HASH, clipsPrefix: CAPTION_PREFIX }, deps);

  expect(debitPayg).not.toHaveBeenCalled();
  expect(recordCogs).not.toHaveBeenCalled();
});
