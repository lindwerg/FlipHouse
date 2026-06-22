import type { ClipInput } from '@fliphouse/db';
import { deriveClipKey, renderManifestSchema } from '@fliphouse/shared';

/** DB writes + R2 read/copy the publish finalizer needs (injectable). */
export interface PublishDeps {
  readJson(key: string): Promise<unknown>;
  /**
   * Server-side R2 copy of a delivered artifact into the durable namespace.
   * Idempotent (overwrites): a re-published clip lands on the same deterministic
   * key, so a retry is a no-op rather than an orphan.
   */
  copyObject(fromKey: string, toKey: string): Promise<void>;
  upsertClips(contentHash: string, rows: readonly ClipInput[]): Promise<void>;
  finishUpload(
    contentHash: string,
    input: { resultUrl: string; manifestUrl: string; engine: string },
  ): Promise<void>;
}

export interface PublishArgs {
  readonly contentHash: string;
  /** R2 prefix the reframe stage wrote its manifest + clips under. */
  readonly reframePrefix: string;
}

/**
 * Durable R2 key for the render manifest, beside the delivered clips under
 * `clips/<hash>/`. The reframe stage writes everything under the EPHEMERAL
 * `intermediate/<hash>/reframe/` prefix (spec: deleted >3 days), so publish must
 * promote the deliverables off it or the ledger URLs would 404 once the
 * lifecycle rule applies.
 */
function durableManifestKey(contentHash: string): string {
  return `clips/${contentHash}/manifest.json`;
}

/**
 * Finalize a render: parse the reframe stage's `manifest.json` (the single source
 * of truth — there is no separate `store`/`result.json` artifact), promote each
 * clip + the manifest from the ephemeral `intermediate/<hash>/reframe/` prefix
 * into the DURABLE `clips/<hash>/` namespace via server-side R2 copy, write the
 * ranked `clips` rows pointing at those durable keys (idempotent upsert keyed on
 * (hash, rank) — a re-publish overwrites the same object and row), then mark the
 * upload done. Copy happens BEFORE the ledger write, so a row never points at a
 * not-yet-copied object; everything is deterministic and crash-safe under retry.
 * (PAYG debit is wired at P5 metering; the idempotent `debitOnce` already exists.)
 */
export async function publishUpload(args: PublishArgs, deps: PublishDeps): Promise<{ clipCount: number }> {
  const manifestKey = `${args.reframePrefix}/manifest.json`;
  const manifest = renderManifestSchema.parse(await deps.readJson(manifestKey));

  const rows: ClipInput[] = [];
  for (const clip of manifest.clips) {
    const sourceKey = `${args.reframePrefix}/${clip.path}`;
    const durableKey = deriveClipKey(args.contentHash, clip.rank);
    await deps.copyObject(sourceKey, durableKey);
    rows.push({
      rank: clip.rank,
      score: String(clip.score),
      subScores: clip.sub_scores,
      confidence: clip.confidence,
      startTime: String(clip.start_time),
      endTime: String(clip.end_time),
      durationS: String(clip.duration_s),
      width: clip.width,
      height: clip.height,
      clipUrl: durableKey,
      title: clip.title,
      usedVideo: clip.used_video,
      modelUsed: clip.model_used,
      modalitiesUsed: clip.modalities_used,
      manifestSchemaVersion: manifest.schema_version,
      engine: manifest.engine,
    });
  }

  const durableManifest = durableManifestKey(args.contentHash);
  await deps.copyObject(manifestKey, durableManifest);

  await deps.upsertClips(args.contentHash, rows);
  await deps.finishUpload(args.contentHash, {
    resultUrl: durableManifest,
    manifestUrl: durableManifest,
    engine: manifest.engine,
  });

  return { clipCount: rows.length };
}
