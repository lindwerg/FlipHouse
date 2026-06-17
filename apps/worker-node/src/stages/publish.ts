import { deriveClipKey, renderManifestSchema } from '@fliphouse/shared';
import type { ClipInput } from '@fliphouse/db';

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
  readonly manifestKey: string;
  readonly resultUrl: string;
}

/**
 * Finalize a render: parse the store stage's `manifest.json`, write the ranked
 * `clips` rows (idempotent upsert keyed on (hash, rank), `clip_url` a pure
 * function of (hash, rank) so a re-publish overwrites rather than orphans), then
 * mark the upload done. The dashboard reads these rows — this is the P2 DoD.
 * (PAYG debit is wired at P5 metering; the idempotent `debitOnce` already exists.)
 */
export async function publishUpload(args: PublishArgs, deps: PublishDeps): Promise<{ clipCount: number }> {
  const manifest = renderManifestSchema.parse(await deps.readJson(args.manifestKey));

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
    clipUrl: deriveClipKey(args.contentHash, clip.rank),
    title: clip.title,
    usedVideo: clip.used_video,
    modelUsed: clip.model_used,
    modalitiesUsed: clip.modalities_used,
    manifestSchemaVersion: manifest.schema_version,
    engine: manifest.engine,
  }));

  await deps.upsertClips(args.contentHash, rows);
  await deps.finishUpload(args.contentHash, {
    resultUrl: args.resultUrl,
    manifestUrl: args.manifestKey,
    engine: manifest.engine,
  });

  return { clipCount: rows.length };
}
