import type { ClipInput } from '@fliphouse/db';
import { renderManifestSchema } from '@fliphouse/shared';

/** DB writes + R2 read the publish finalizer needs (injectable). */
export interface PublishDeps {
  readJson(key: string): Promise<unknown>;
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

/** The R2 key of a clip = the producer's own key (reframe prefix + bare path). */
function resolveClipKey(reframePrefix: string, clipPath: string): string {
  return `${reframePrefix}/${clipPath}`;
}

/**
 * Finalize a render: parse the reframe stage's `manifest.json` (the single source
 * of truth — there is no separate `store`/`result.json` artifact), write the
 * ranked `clips` rows (idempotent upsert keyed on (hash, rank); `clip_url` is the
 * producer's actual R2 key so a re-publish overwrites rather than orphans), then
 * mark the upload done. The dashboard reads these rows — this is the P2 DoD.
 * (PAYG debit is wired at P5 metering; the idempotent `debitOnce` already exists.)
 */
export async function publishUpload(args: PublishArgs, deps: PublishDeps): Promise<{ clipCount: number }> {
  const manifestKey = `${args.reframePrefix}/manifest.json`;
  const manifest = renderManifestSchema.parse(await deps.readJson(manifestKey));

  const rows: ClipInput[] = manifest.clips.map((clip) => ({
    rank: clip.rank,
    score: String(clip.score),
    subScores: clip.sub_scores,
    confidence: clip.confidence,
    startTime: String(clip.start_time),
    endTime: String(clip.end_time),
    durationS: String(clip.duration_s),
    width: clip.width,
    height: clip.height,
    clipUrl: resolveClipKey(args.reframePrefix, clip.path),
    title: clip.title,
    usedVideo: clip.used_video,
    modelUsed: clip.model_used,
    modalitiesUsed: clip.modalities_used,
    manifestSchemaVersion: manifest.schema_version,
    engine: manifest.engine,
  }));

  await deps.upsertClips(args.contentHash, rows);
  await deps.finishUpload(args.contentHash, {
    // The manifest IS the canonical result artifact now that result.json is gone.
    resultUrl: manifestKey,
    manifestUrl: manifestKey,
    engine: manifest.engine,
  });

  return { clipCount: rows.length };
}
