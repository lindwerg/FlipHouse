import type { ClipInput, UploadCharge } from '@fliphouse/db';
import { ratePaygMicros } from '@fliphouse/db';
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
  /** Load the upload's owner + probed source duration to compute the PAYG charge. */
  loadUpload(contentHash: string): Promise<UploadCharge | null>;
  /** Charge the prepaid balance, idempotent on (userId, jobId=contentHash). */
  debitPayg(input: { userId: string; jobId: string; amountMicros: bigint }): Promise<boolean>;
  /** Persist the COGS row to the separate sink, idempotent on contentHash. */
  recordCogs(input: {
    contentHash: string;
    ownerId: string;
    costUsdMicros: bigint;
    engine?: string;
  }): Promise<void>;
}

/**
 * COGS recorded per published upload, in micro-USD. Pinned to 0 for now: the
 * Python manifest cost-threading is a documented follow-up (fail-open — the
 * sink + idempotent row ship now, the real number lands later).
 */
const COGS_MICROS_PLACEHOLDER = 0n;

export interface PublishArgs {
  readonly contentHash: string;
  /**
   * R2 prefix the LAST clip-producing stage wrote its manifest + `clip_NN.mp4`
   * under. This is now the `caption` stage (the real burn-in, P2 step 5), which
   * re-emits the manifest + the captioned clips — so publish promotes the
   * CAPTIONED deliverables, not the bare reframe ones.
   */
  readonly clipsPrefix: string;
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
 * Finalize a render: parse the caption stage's `manifest.json` (the single source
 * of truth — there is no separate `store`/`result.json` artifact), promote each
 * clip + the manifest from the ephemeral `intermediate/<hash>/caption/` prefix
 * into the DURABLE `clips/<hash>/` namespace via server-side R2 copy, write the
 * ranked `clips` rows pointing at those durable keys (idempotent upsert keyed on
 * (hash, rank) — a re-publish overwrites the same object and row), then mark the
 * upload done. Copy happens BEFORE the ledger write, so a row never points at a
 * not-yet-copied object; everything is deterministic and crash-safe under retry.
 *
 * S7 BILLING — charge ONLY here, the terminal-success seam: a failed/aborted flow
 * never reaches publish, so a debit never fires on failure. The PAYG charge is
 * computed from the probed source duration and debited via {@link PublishDeps.debitPayg}
 * keyed on (ownerId, jobId=contentHash) — so a re-published upload charges EXACTLY
 * ONCE (the ledger's ON CONFLICT makes the duplicate a no-op). The balance may dip
 * negative: the job is already done, and the pre-submit gate guards starts. COGS is
 * recorded to the separate sink alongside (idempotent on contentHash, 0 for now).
 */
export async function publishUpload(args: PublishArgs, deps: PublishDeps): Promise<{ clipCount: number }> {
  const manifestKey = `${args.clipsPrefix}/manifest.json`;
  const manifest = renderManifestSchema.parse(await deps.readJson(manifestKey));

  const rows: ClipInput[] = [];
  for (const clip of manifest.clips) {
    const sourceKey = `${args.clipsPrefix}/${clip.path}`;
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

  await chargeAndRecordCost(args.contentHash, manifest.engine, deps);

  return { clipCount: rows.length };
}

/**
 * Charge the PAYG fee and record COGS, both AFTER the upload is durably finished.
 * The ledger row is the source of truth for the owner + duration (not the job
 * payload). A missing ledger row (`loadUpload` → null) means the upload vanished
 * out from under a completed publish — there is nothing to bill against, so we
 * skip rather than charge a guessed owner. A `null` duration falls back to 0,
 * which {@link ratePaygMicros} floors to the 1-minute minimum (never free).
 */
async function chargeAndRecordCost(
  contentHash: string,
  engine: string,
  deps: PublishDeps,
): Promise<void> {
  const upload = await deps.loadUpload(contentHash);
  if (!upload) {
    return;
  }
  const amountMicros = ratePaygMicros(upload.durationSec ?? 0);
  await deps.debitPayg({ userId: upload.ownerId, jobId: contentHash, amountMicros });
  await deps.recordCogs({
    contentHash,
    ownerId: upload.ownerId,
    costUsdMicros: COGS_MICROS_PLACEHOLDER,
    engine,
  });
}
