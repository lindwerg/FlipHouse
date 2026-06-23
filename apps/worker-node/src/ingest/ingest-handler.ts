import type { ClaimInput, ClaimResult, UploadRow } from '@fliphouse/db';
import { flowJobId, isValidContentHash } from '@fliphouse/shared';

import type { EnqueueArgs } from './ingest-types.js';

/**
 * URL-ingestion handler — the worker-side mirror of the tusd post-finish
 * (apps/hook-receiver/handle-post-finish.ts), but the SOURCE bytes arrive via a
 * yt-dlp download instead of a browser tus upload.
 *
 * Flow: download the URL → content-hash the bytes → write the R2 source object
 * (content-addressed: `sources/<hash>.mp4`) → atomically CLAIM the ledger by
 * content-hash → enqueue the SAME transcode→…→publish render flow → mark it
 * enqueued. Every effect is injected so the orchestration is unit-tested with no
 * yt-dlp, no R2, and no pg/Redis.
 *
 * Idempotency: the durable ON CONFLICT ledger claim — not the download — gates the
 * enqueue. A duplicate URL whose bytes hash to an already-claimed upload is a
 * no-op (no re-enqueue). A download failure throws a LOUD classified error BEFORE
 * any claim, so a failed ingest never leaves a half-claimed row.
 */

/** The R2 key prefix every ingested source video lands under (content-addressed). */
const SOURCE_KEY_PREFIX = 'sources';

/** Content type stamped on the ingested source object (yt-dlp merges to mp4). */
const SOURCE_CONTENT_TYPE = 'video/mp4';

/** Deterministic R2 key for an ingested source video, keyed by content-hash. */
export function sourceKey(contentHash: string): string {
  return `${SOURCE_KEY_PREFIX}/${contentHash}.mp4`;
}

/** All side-effecting boundaries of one ingest, injected for unit testing. */
export interface IngestDeps {
  /** Download the URL to a local path (throws a loud IngestDownloadError on failure). */
  download(url: string, localPath: string): Promise<void>;
  /** SHA-256 hex of the downloaded bytes — the content identity / ledger PK. */
  hashFile(localPath: string): Promise<string>;
  /** Stream the local file to R2 under `key` with the given content type. */
  putFile(localPath: string, key: string, contentType: string): Promise<void>;
  /** Atomically claim the upload by content-hash (ON CONFLICT idempotency). */
  claimUpload(input: ClaimInput): Promise<ClaimResult>;
  /** Enqueue the render flow for this upload (FlowProducer dedups a re-add). */
  enqueueFlow(args: EnqueueArgs): Promise<void>;
  /** Persist the flow's root jobId, marking the upload's flow as enqueued. */
  markEnqueued(contentHash: string): Promise<void>;
  /** Allocate a temp path for the download (removed by the caller after the job). */
  tempPath(): string;
  /** Best-effort cleanup of the downloaded temp file (never throws). */
  cleanup(localPath: string): Promise<void>;
}

export type IngestOutcome =
  | { readonly kind: 'enqueued'; readonly contentHash: string }
  | { readonly kind: 'duplicate'; readonly contentHash: string; readonly existing: UploadRow | undefined };

export interface IngestInput {
  readonly url: string;
  readonly ownerId: string;
}

/**
 * Run one URL ingest end-to-end. Returns `enqueued` for a fresh upload or
 * `duplicate` when the content was already claimed (same bytes, idempotent). The
 * temp download is ALWAYS cleaned up (success or throw) via a finally guard so a
 * long-running worker never leaks disk. A download failure propagates the loud
 * classified IngestDownloadError to the BullMQ job (recorded + surfaced).
 */
export async function runIngest(input: IngestInput, deps: IngestDeps): Promise<IngestOutcome> {
  const localPath = deps.tempPath();
  try {
    await deps.download(input.url, localPath);

    const contentHash = await deps.hashFile(localPath);
    // Defence in depth: the streamed sha256 must be a real 64-hex digest before it
    // becomes a Postgres PK / BullMQ jobId. A bad hash is a programmer error, not a
    // user error — fail loud rather than corrupt the ledger.
    if (!isValidContentHash(contentHash)) {
      throw new Error(`ingest produced an invalid content hash: ${contentHash}`);
    }

    const key = sourceKey(contentHash);
    await deps.putFile(localPath, key, SOURCE_CONTENT_TYPE);

    const claim = await deps.claimUpload({
      contentHash,
      ownerId: input.ownerId,
      firstUploadId: `ingest:${contentHash}`,
      tusObjectKey: key,
    });
    if (!claim.claimed) {
      return { kind: 'duplicate', contentHash, existing: claim.existing };
    }

    await deps.enqueueFlow({ contentHash, ownerId: input.ownerId, source: key });
    await deps.markEnqueued(contentHash);
    return { kind: 'enqueued', contentHash };
  } finally {
    await deps.cleanup(localPath);
  }
}

/** Bind {@link IngestDeps.markEnqueued} to the canonical content-derived flow jobId. */
export function ingestFlowJobId(contentHash: string): string {
  return flowJobId(contentHash);
}
