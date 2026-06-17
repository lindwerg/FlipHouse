import { UnrecoverableError } from 'bullmq';
import type { FailureKind, StageResult } from '@fliphouse/shared';

/** The failure variant of a {@link StageResult}. */
export type StageFailure = Extract<StageResult, { ok: false }>;

/**
 * Map a failure kind to the BullMQ error a worker should throw.
 *
 * This mapping is LOAD-BEARING: a `fatal` thrown as a plain `Error` would be
 * retried `attempts` times (e.g. hammering an OpenRouter 402), and a `retryable`
 * thrown as `UnrecoverableError` would skip legitimate retries. Both branches
 * are tested.
 */
export function toBullError(kind: FailureKind, code: string, message: string): Error {
  const text = `${code}: ${message}`;
  return kind === 'fatal' ? new UnrecoverableError(text) : new Error(text);
}

/** Build the BullMQ error for a failed stage result, preserving its kind. */
export function stageErrorFrom(failure: StageFailure): Error {
  return toBullError(failure.kind, failure.code, failure.message);
}
