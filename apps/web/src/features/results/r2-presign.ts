import { GetObjectCommand, S3Client } from '@aws-sdk/client-s3';
import type { S3ClientConfig } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';
import { Env } from '@/libs/Env';

// Private-bucket clip serving (P2.3). The clip bucket is private-read, so the
// worker stores each clip's R2 object KEY (e.g. clips/<hash>/rank-1.mp4) in
// clips.clipUrl and the dashboard turns that key into a short-lived presigned
// GET URL here — server-side, on the Node runtime (presigning needs node crypto).
//
// This mirrors the worker's buildS3Config seam: the load-bearing WHEN_REQUIRED
// checksum knobs are mandatory for S3-compat (aws-sdk v3's WHEN_SUPPORTED default
// emits a CRC32 streaming trailer R2/Railway Buckets reject). The live S3Client
// is constructed once, lazily, and that construction is the ONLY untestable glue
// (v8-ignored); the presign LOGIC — key normalisation, command shape, ttl — is
// unit-tested by mocking getSignedUrl.

/** Presigned-GET lifetime: 6 hours. Long enough for a dashboard session/download. */
export const CLIP_URL_TTL_SECONDS = 21600;

/** R2 connection settings, validated out of {@link Env}. */
export interface R2Settings {
  /** Omitted when `endpoint` is supplied (a non-Cloudflare S3 store). */
  readonly accountId?: string;
  /** Explicit S3 endpoint override (e.g. Railway Buckets, https://t3.storageapi.dev). */
  readonly endpoint?: string;
  readonly bucket: string;
  readonly accessKeyId: string;
  readonly secretAccessKey: string;
}

/** Subset of {@link Env} this module reads — accepted as a param so it is testable. */
interface R2Env {
  readonly R2_ENDPOINT?: string;
  readonly R2_BUCKET: string;
  readonly R2_ACCESS_KEY_ID: string;
  readonly R2_SECRET_ACCESS_KEY: string;
  readonly R2_ACCOUNT_ID?: string;
}

/**
 * Resolve R2 settings from validated env. Endpoint resolution mirrors the
 * worker: a non-empty `R2_ENDPOINT` targets a non-Cloudflare store (account id
 * not required); otherwise `R2_ACCOUNT_ID` is required and the Cloudflare R2 URL
 * is derived from it in {@link buildR2PresignConfig}. An empty-string endpoint
 * counts as absent.
 */
export function resolveR2Settings(env: R2Env): R2Settings {
  const base = {
    bucket: env.R2_BUCKET,
    accessKeyId: env.R2_ACCESS_KEY_ID,
    secretAccessKey: env.R2_SECRET_ACCESS_KEY,
  };
  if (env.R2_ENDPOINT) {
    return { ...base, endpoint: env.R2_ENDPOINT };
  }
  if (!env.R2_ACCOUNT_ID) {
    throw new Error('missing required env var: R2_ACCOUNT_ID');
  }
  return { ...base, accountId: env.R2_ACCOUNT_ID };
}

/**
 * S3 client config for the private clip bucket. `WHEN_REQUIRED` on both checksum
 * knobs is mandatory (see file header). `endpoint` falls back to the Cloudflare
 * R2 URL when no override is supplied. The aws-sdk v3 default
 * `forcePathStyle: false` (virtual-hosted-style) is correct for both Cloudflare
 * R2 and the supported non-Cloudflare stores, so it is deliberately left unset.
 */
export function buildR2PresignConfig(settings: R2Settings): S3ClientConfig {
  return {
    region: 'auto',
    endpoint: settings.endpoint ?? `https://${settings.accountId}.r2.cloudflarestorage.com`,
    credentials: {
      accessKeyId: settings.accessKeyId,
      secretAccessKey: settings.secretAccessKey,
    },
    requestChecksumCalculation: 'WHEN_REQUIRED',
    responseChecksumValidation: 'WHEN_REQUIRED',
  };
}

// Lazy singleton: the S3Client pools connections internally, so it is built once
// per server process and shared across every presign call.
let cachedClient: S3Client | undefined;

/* v8 ignore start -- thin glue: real S3Client construction, exercised by integration not unit tests */
function getClient(): S3Client {
  cachedClient ??= new S3Client(buildR2PresignConfig(resolveR2Settings(Env)));
  return cachedClient;
}
/* v8 ignore stop */

/**
 * Turn a stored R2 object key into a short-lived presigned GET URL. A leading
 * slash on the key is stripped so the signed key matches the stored object
 * exactly. The URL is valid for {@link CLIP_URL_TTL_SECONDS}.
 */
export async function presignClipUrl(key: string): Promise<string> {
  const normalisedKey = key.replace(/^\/+/, '');
  const command = new GetObjectCommand({ Bucket: Env.R2_BUCKET, Key: normalisedKey });
  return getSignedUrl(getClient(), command, { expiresIn: CLIP_URL_TTL_SECONDS });
}
