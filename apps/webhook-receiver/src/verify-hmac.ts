import { createHmac, timingSafeEqual } from 'node:crypto';

/**
 * HMAC-SHA256 verification of a raw GigaAM-v3 callback (P2 step #1, TRACK B). The
 * provider signs `${timestamp}.${rawBody}` — binding the exact request bytes to a
 * wall-clock so a captured callback cannot be replayed outside a narrow window —
 * and we recompute and compare in **constant time** so a wrong signature cannot
 * be teased out by timing.
 *
 * Invariants: this module is 100% pure (no mutation; the only ambient read is the
 * injected `nowSec` clock), and it NEVER throws on bad input — every malformed
 * header, digest, timestamp, or stale/skewed callback funnels to `false`, so the
 * caller branches on a boolean instead of catching.
 */

const SIGNATURE_PREFIX = 'sha256=';
const HEX_DIGEST_RE = /^[0-9a-f]+$/;

/** Symmetric ±window (seconds) a callback timestamp may deviate from our clock. */
export const REPLAY_WINDOW_SEC = 300;

/**
 * Pull the hex digest out of a `sha256=<hex>` header. Returns `undefined` when
 * the prefix is missing or the remainder is not lowercase hex — kept separate
 * from {@link verifyHmac} so the parsing branch is independently testable.
 */
export function extractHexDigest(header: string): string | undefined {
  if (!header.startsWith(SIGNATURE_PREFIX)) {
    return undefined;
  }
  const digest = header.slice(SIGNATURE_PREFIX.length);
  if (digest.length === 0 || !HEX_DIGEST_RE.test(digest)) {
    return undefined;
  }
  return digest;
}

/**
 * Parse a unix-seconds timestamp header into an integer. Returns `undefined` for
 * an empty, non-numeric, or non-integer value — a malformed timestamp can never
 * pass the replay check, so it short-circuits to a rejected verification.
 */
export function parseTimestamp(header: string): number | undefined {
  if (header.length === 0 || !/^-?\d+$/.test(header)) {
    return undefined;
  }
  return Number.parseInt(header, 10);
}

/** True when `timestamp` is within ±{@link REPLAY_WINDOW_SEC} of `nowSec`. */
export function isWithinReplayWindow(timestamp: number, nowSec: number): boolean {
  return Math.abs(nowSec - timestamp) <= REPLAY_WINDOW_SEC;
}

export interface VerifyHmacArgs {
  readonly secret: string;
  readonly rawBody: string;
  readonly signatureHeader: string;
  readonly timestampHeader: string;
  /** Injected clock (unix seconds). Defaults to wall-clock; overridable in tests. */
  readonly nowSec?: number;
}

/**
 * Verify `signatureHeader` against the HMAC-SHA256 of `${timestamp}.${rawBody}`
 * under `secret`, AND enforce the ±{@link REPLAY_WINDOW_SEC} replay window on
 * `timestampHeader`. Uses {@link timingSafeEqual} for the comparison; because
 * that throws on length-mismatched buffers, an explicit length guard
 * short-circuits a truncated digest to `false` instead of letting it throw.
 */
export function verifyHmac(args: VerifyHmacArgs): boolean {
  const { secret, rawBody, signatureHeader, timestampHeader } = args;
  const nowSec = args.nowSec ?? Math.floor(Date.now() / 1000);

  const provided = extractHexDigest(signatureHeader);
  if (provided === undefined) {
    return false;
  }
  const timestamp = parseTimestamp(timestampHeader);
  if (timestamp === undefined || !isWithinReplayWindow(timestamp, nowSec)) {
    return false;
  }
  const signedMessage = `${timestamp}.${rawBody}`;
  const expected = createHmac('sha256', secret).update(signedMessage).digest('hex');
  if (provided.length !== expected.length) {
    return false;
  }
  return timingSafeEqual(Buffer.from(provided, 'hex'), Buffer.from(expected, 'hex'));
}
