import {
  CopyObjectCommand,
  GetObjectCommand,
  HeadObjectCommand,
  PutObjectCommand,
} from '@aws-sdk/client-s3';
import type { S3Client, S3ClientConfig } from '@aws-sdk/client-s3';

import type { ArtifactStore } from '../stages/handler-contract.js';

/** Version stamped into every sentinel body, so an operator can read its shape. */
export const SENTINEL_SCHEMA_VERSION = 1;

/**
 * Hard ceiling on the sentinel body. A test-enforced invariant: keeping the body
 * tiny guarantees a single-part PUT, which is what makes the `IfNoneMatch: '*'`
 * conditional-write atomic (the precondition does NOT hold for multipart). A dev
 * who grows the marker past this hits a failing test, not a silent regression.
 */
export const SENTINEL_MAX_BYTES = 1024;

/** Object written LAST under a stage's output prefix to mark it complete. */
const SENTINEL_NAME = '_COMPLETE.json';

/** Fatal marker the asr-resume consumer writes under the prefix on an `asr-fail`. */
const FAILED_MARKER_NAME = '_FAILED.json';

export interface R2Credentials {
  /** Omitted when `endpoint` is supplied (a non-Cloudflare S3 store). */
  readonly accountId?: string;
  /**
   * Explicit S3 endpoint override (e.g. Railway Buckets,
   * `https://t3.storageapi.dev`). When set it is used verbatim; otherwise the
   * Cloudflare R2 URL is derived from `accountId`.
   */
  readonly endpoint?: string;
  readonly accessKeyId: string;
  readonly secretAccessKey: string;
}

/**
 * S3 client config for an S3-compatible store. `WHEN_REQUIRED` on both checksum
 * knobs is mandatory: aws-sdk-js v3's default (`WHEN_SUPPORTED`) emits a CRC32
 * streaming trailer R2 rejects with `SignatureDoesNotMatch` — the exact mirror
 * of the boto3-1.36 fix in the Python `stages/r2.py` seam.
 *
 * `endpoint` falls back to the Cloudflare R2 URL when no override is supplied.
 * The aws-sdk v3 default `forcePathStyle: false` (virtual-hosted-style) is
 * correct for both Cloudflare R2 and the supported non-Cloudflare stores, so it
 * is deliberately left unset.
 */
export function buildS3Config(creds: R2Credentials): S3ClientConfig {
  return {
    region: 'auto',
    endpoint: creds.endpoint ?? `https://${creds.accountId}.r2.cloudflarestorage.com`,
    credentials: { accessKeyId: creds.accessKeyId, secretAccessKey: creds.secretAccessKey },
    requestChecksumCalculation: 'WHEN_REQUIRED',
    responseChecksumValidation: 'WHEN_REQUIRED',
  };
}

interface AwsErrorShape {
  readonly $metadata?: { readonly httpStatusCode?: number };
  readonly name?: string;
}

/** A genuine "object isn't there" — the ONLY case `hasSentinel` maps to false. */
export function isNotFound(err: unknown): boolean {
  const e = err as AwsErrorShape | null | undefined;
  return e?.$metadata?.httpStatusCode === 404 || e?.name === 'NotFound';
}

/** A conditional-write precondition failure — a second writer lost the race. */
export function isPreconditionFailed(err: unknown): boolean {
  const e = err as AwsErrorShape | null | undefined;
  return e?.$metadata?.httpStatusCode === 412 || e?.name === 'PreconditionFailed';
}

function isConflict(err: unknown): boolean {
  return (err as AwsErrorShape | null | undefined)?.$metadata?.httpStatusCode === 409;
}

/**
 * Concrete {@link ArtifactStore} over Cloudflare R2. The sentinel — never a bare
 * data object — is the authority on "stage already done": a data HEAD could be a
 * truncated partial, so existence is checked ONLY against `_COMPLETE.json`.
 *
 * The single network seam is the injected `s3Client.send`, so the whole class is
 * unit-testable with a mock and needs no coverage-ignore.
 */
export class R2ArtifactStore implements ArtifactStore {
  readonly #bucket: string;
  readonly #s3Client: S3Client;

  constructor({ bucket, s3Client }: { bucket: string; s3Client: S3Client }) {
    this.#bucket = bucket;
    this.#s3Client = s3Client;
  }

  async hasSentinel(outputPrefix: string): Promise<boolean> {
    const Key = `${outputPrefix}/${SENTINEL_NAME}`;
    try {
      await this.#s3Client.send(new HeadObjectCommand({ Bucket: this.#bucket, Key }));
      return true;
    } catch (err: unknown) {
      // A 404 means "not done yet". A 403/5xx/network error MUST propagate, or a
      // broken R2 config would read as "not done" and the stage re-runs forever.
      if (isNotFound(err)) return false;
      throw err;
    }
  }

  async writeSentinel(outputPrefix: string, marker: Record<string, unknown>): Promise<void> {
    const body = JSON.stringify({
      ...marker,
      completedAt: new Date().toISOString(),
      schemaVersion: SENTINEL_SCHEMA_VERSION,
    });
    if (Buffer.byteLength(body, 'utf8') > SENTINEL_MAX_BYTES) {
      throw new Error(`sentinel body exceeds SENTINEL_MAX_BYTES (${SENTINEL_MAX_BYTES} bytes)`);
    }
    const Key = `${outputPrefix}/${SENTINEL_NAME}`;
    try {
      await this.#s3Client.send(
        new PutObjectCommand({
          Bucket: this.#bucket,
          Key,
          Body: body,
          ContentType: 'application/json',
          IfNoneMatch: '*',
        }),
      );
    } catch (err: unknown) {
      // Write-once: a concurrent first-writer-wins (412) or a delete+rewrite race
      // (409) means the sentinel already exists — an idempotent no-op, not a failure.
      if (isPreconditionFailed(err) || isConflict(err)) return;
      throw err;
    }
  }

  /** True iff the asr `_FAILED` marker exists under the prefix (HEAD, 404 → false). */
  async hasFailedMarker(outputPrefix: string): Promise<boolean> {
    const Key = `${outputPrefix}/${FAILED_MARKER_NAME}`;
    try {
      await this.#s3Client.send(new HeadObjectCommand({ Bucket: this.#bucket, Key }));
      return true;
    } catch (err: unknown) {
      if (isNotFound(err)) return false;
      throw err;
    }
  }

  /**
   * Write the asr `_FAILED` marker carrying the provider error. Write-once via
   * `IfNoneMatch: '*'` — a duplicate `asr-fail` (412/409) is an idempotent no-op,
   * so the first error text wins and a retry never overwrites or errors.
   */
  async writeFailedMarker(outputPrefix: string, error: string): Promise<void> {
    const body = JSON.stringify({ error, failedAt: new Date().toISOString() });
    const Key = `${outputPrefix}/${FAILED_MARKER_NAME}`;
    try {
      await this.#s3Client.send(
        new PutObjectCommand({
          Bucket: this.#bucket,
          Key,
          Body: body,
          ContentType: 'application/json',
          IfNoneMatch: '*',
        }),
      );
    } catch (err: unknown) {
      if (isPreconditionFailed(err) || isConflict(err)) return;
      throw err;
    }
  }

  /** Read the error string out of the `_FAILED` marker (for the thrown fatal error). */
  async readFailedError(outputPrefix: string): Promise<string> {
    const parsed = (await this.getJson(`${outputPrefix}/${FAILED_MARKER_NAME}`)) as { error?: unknown };
    return typeof parsed.error === 'string' ? parsed.error : 'unknown';
  }

  /**
   * Server-side copy one object to another key within the same bucket — used by
   * publish to promote a delivered clip/manifest off the ephemeral
   * `intermediate/` prefix into the durable `clips/` namespace without streaming
   * bytes through the worker. `CopySource` MUST be URL-encoded so keys with `/`
   * (every key here) and any reserved chars survive. Idempotent: re-copy
   * overwrites the same deterministic destination.
   */
  async copyObject(fromKey: string, toKey: string): Promise<void> {
    await this.#s3Client.send(
      new CopyObjectCommand({
        Bucket: this.#bucket,
        CopySource: encodeURI(`${this.#bucket}/${fromKey}`),
        Key: toKey,
      }),
    );
  }

  /**
   * Fetch a JSON object and parse it. Used by the publish finalizer to read the
   * render manifest. A missing object propagates the SDK error (404 → BullMQ
   * retry/fatal as classified upstream); a present-but-empty body is a hard error.
   */
  async getJson(key: string): Promise<unknown> {
    const res = await this.#s3Client.send(new GetObjectCommand({ Bucket: this.#bucket, Key: key }));
    if (!res.Body) {
      throw new Error(`R2 object has no body: ${key}`);
    }
    return JSON.parse(await res.Body.transformToString()) as unknown;
  }
}
