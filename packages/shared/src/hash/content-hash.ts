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
 * Characters BullMQ tolerates in a custom jobId. BullMQ composes Redis keys as
 * `bull:<queue>:<jobId>`, so a `:` in the id corrupts key parsing — the spec's
 * original `flow:${hash}` form is illegal. Restricted to `[A-Za-z0-9._-]`.
 */
export const BULLMQ_JOBID_RE = /^[A-Za-z0-9._-]+$/;

/** True when `value` is a 64-char lowercase hex SHA-256 digest. */
export function isValidContentHash(value: string): boolean {
  return /^[0-9a-f]{64}$/.test(value);
}

/**
 * Assert a derived id is a legal BullMQ custom jobId, failing fast at the
 * boundary so a malformed id never silently corrupts Redis key routing.
 */
function assertLegalJobId(jobId: string): string {
  if (!BULLMQ_JOBID_RE.test(jobId)) {
    throw new Error(`illegal BullMQ jobId "${jobId}": must match ${String(BULLMQ_JOBID_RE)}`);
  }
  return jobId;
}

/**
 * Deterministic BullMQ jobId for the ROOT of a content's render flow. The
 * `flow-` prefix (not the spec's illegal `flow:`) keeps the id Redis-key-safe
 * while still making a re-add of the same content a no-op (docs/01 §5).
 */
export function flowJobId(hash: string): string {
  return assertLegalJobId(`flow-${hash}`);
}

/**
 * Deterministic BullMQ jobId for a single STAGE of a content's render flow.
 * `${stage}-${hash}` lets a re-added flow dedup per node, not just at the root.
 */
export function stageJobId(stage: string, hash: string): string {
  return assertLegalJobId(`${stage}-${hash}`);
}
