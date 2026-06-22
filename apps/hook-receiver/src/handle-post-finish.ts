import type { ClaimInput, ClaimResult, UploadRow } from '@fliphouse/db';
import { isValidContentHash } from '@fliphouse/shared';

import { tusdPostFinishSchema } from './tusd-types.js';

/** What a single upload's flow enqueue needs (kept local to avoid app coupling). */
export interface EnqueueArgs {
  readonly contentHash: string;
  readonly ownerId: string;
  readonly source: string;
}

export interface PostFinishDeps {
  claimUpload(input: ClaimInput): Promise<ClaimResult>;
  enqueueFlow(args: EnqueueArgs): Promise<void>;
  /**
   * Mark the flow as enqueued (persist its root jobId). Called AFTER a successful
   * enqueue so the reconcile-sweep can tell "never enqueued" (marker absent) from
   * "enqueued, just slow" (marker present). A crash between enqueue and mark
   * leaves the marker absent → the sweep re-enqueues, which the FlowProducer
   * dedups (idempotent). Marking BEFORE enqueue would instead risk losing a flow.
   */
  markEnqueued(contentHash: string): Promise<void>;
}

export type PostFinishOutcome =
  | { readonly kind: 'enqueued'; readonly contentHash: string }
  | { readonly kind: 'duplicate'; readonly contentHash: string; readonly existing: UploadRow | undefined }
  | { readonly kind: 'hash-required'; readonly uploadId: string }
  | { readonly kind: 'invalid-payload' }
  | { readonly kind: 'missing-owner'; readonly uploadId: string };

/**
 * Translate a tusd post-finish into a render flow, idempotently. The durable
 * `upload_ledger` ON CONFLICT claim — NOT the BullMQ jobId — gates the enqueue:
 * only the caller that wins the claim enqueues, so a re-delivered hook or a
 * concurrent re-upload of the same bytes is a no-op. A crash between claim and
 * enqueue is recovered by the reconcile-sweep (findStuckFlows).
 *
 * Client-contract violations (malformed envelope, missing ownerId, no sha256)
 * return a typed outcome the router maps to a 4xx — they are NOT thrown, so they
 * never read as a 5xx. A thrown error is reserved for genuine infra failure
 * (pg/Redis), the only case a tusd hook should treat as retryable.
 */
export async function handlePostFinish(
  payload: unknown,
  deps: PostFinishDeps,
): Promise<PostFinishOutcome> {
  const parsed = tusdPostFinishSchema.safeParse(payload);
  if (!parsed.success) {
    return { kind: 'invalid-payload' };
  }
  const upload = parsed.data.Event.Upload;

  const ownerId = upload.MetaData.ownerId;
  if (ownerId === undefined || ownerId.length === 0) {
    return { kind: 'missing-owner', uploadId: upload.ID };
  }

  const contentHash = upload.MetaData.sha256 ?? '';
  if (!isValidContentHash(contentHash)) {
    // Client did not stream a valid sha256 → server-verified hashing required.
    return { kind: 'hash-required', uploadId: upload.ID };
  }

  const claim = await deps.claimUpload({
    contentHash,
    ownerId,
    firstUploadId: upload.ID,
    tusObjectKey: upload.Storage.Key,
    sizeBytes: upload.Size,
  });
  if (!claim.claimed) {
    return { kind: 'duplicate', contentHash, existing: claim.existing };
  }

  await deps.enqueueFlow({ contentHash, ownerId, source: upload.Storage.Key });
  await deps.markEnqueued(contentHash);
  return { kind: 'enqueued', contentHash };
}
