import { isValidContentHash } from '@fliphouse/shared';
import type { ClaimInput, ClaimResult, UploadRow } from '@fliphouse/db';

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
}

export type PostFinishOutcome =
  | { readonly kind: 'enqueued'; readonly contentHash: string }
  | { readonly kind: 'duplicate'; readonly contentHash: string; readonly existing: UploadRow | undefined }
  | { readonly kind: 'hash-required'; readonly uploadId: string };

/**
 * Translate a tusd post-finish into a render flow, idempotently. The durable
 * `upload_ledger` ON CONFLICT claim — NOT the BullMQ jobId — gates the enqueue:
 * only the caller that wins the claim enqueues, so a re-delivered hook or a
 * concurrent re-upload of the same bytes is a no-op. A crash between claim and
 * enqueue is recovered by the reconcile-sweep (findStuckFlows).
 */
export async function handlePostFinish(
  payload: unknown,
  deps: PostFinishDeps,
): Promise<PostFinishOutcome> {
  const upload = tusdPostFinishSchema.parse(payload).Event.Upload;

  const ownerId = upload.MetaData.ownerId;
  if (ownerId === undefined || ownerId.length === 0) {
    throw new Error('post-finish payload missing ownerId metadata');
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
  return { kind: 'enqueued', contentHash };
}
