import { createHmac, timingSafeEqual } from 'node:crypto';

/**
 * HMAC-SHA256 verification of a raw GPU-callback body (spec §6.12). The provider
 * signs the exact request bytes; we recompute and compare in **constant time**
 * so a wrong signature cannot be teased out by timing. Invariants: this module
 * is 100% pure (no I/O, no mutation) and NEVER throws on bad input — every
 * malformed header or digest funnels to `false`, so the caller can branch on a
 * boolean instead of catching.
 */

const SIGNATURE_PREFIX = 'sha256=';
const HEX_DIGEST_RE = /^[0-9a-f]+$/;

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
 * Verify `signatureHeader` against the HMAC-SHA256 of `rawBody` under `secret`.
 * Uses {@link timingSafeEqual} for the comparison; because that throws on
 * length-mismatched buffers, an explicit length guard short-circuits a
 * truncated digest to `false` instead of letting it throw.
 */
export function verifyHmac(secret: string, rawBody: string, signatureHeader: string): boolean {
  const provided = extractHexDigest(signatureHeader);
  if (provided === undefined) {
    return false;
  }
  const expected = createHmac('sha256', secret).update(rawBody).digest('hex');
  if (provided.length !== expected.length) {
    return false;
  }
  return timingSafeEqual(Buffer.from(provided, 'hex'), Buffer.from(expected, 'hex'));
}
