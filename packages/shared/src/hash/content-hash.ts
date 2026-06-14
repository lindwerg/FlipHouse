import { createHash } from 'node:crypto';

/**
 * SHA-256 of the given bytes as a 64-char lowercase hex string.
 * This hash is the content identity used as the Postgres PK and BullMQ jobId
 * (docs/01 §5 — idempotency by content-hash).
 */
export function sha256Hex(bytes: Uint8Array): string {
  return createHash('sha256').update(bytes).digest('hex');
}

/**
 * BullMQ jobId derived from a content hash. The `flow:` prefix is spec-mandated
 * (docs/01 §5: `jobId = flow:${hash}`) so re-adding the same id is a no-op.
 */
export function jobIdFromHash(hash: string): string {
  return `flow:${hash}`;
}
