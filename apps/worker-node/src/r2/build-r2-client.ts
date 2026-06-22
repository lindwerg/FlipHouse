import { S3Client } from '@aws-sdk/client-s3';

import { R2ArtifactStore, buildS3Config } from './artifact-store.js';

/** R2 connection settings, validated out of the process environment. */
export interface R2Settings {
  /** Omitted when `endpoint` is supplied (a non-Cloudflare S3 store). */
  readonly accountId?: string;
  /** Explicit S3 endpoint override (e.g. Railway Buckets); see {@link resolveR2Env}. */
  readonly endpoint?: string;
  readonly bucket: string;
  readonly accessKeyId: string;
  readonly secretAccessKey: string;
}

/** Always required, regardless of how the endpoint is resolved. */
const REQUIRED_VARS = ['R2_BUCKET', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY'] as const;

/**
 * Validate R2 env vars into typed settings, failing fast (at process start, on
 * Railway) with a message naming the first missing var. An empty string counts
 * as missing — a blank secret is never a valid credential.
 *
 * Endpoint resolution: when `R2_ENDPOINT` is set (non-empty), it targets a
 * non-Cloudflare S3-compatible store and `R2_ACCOUNT_ID` is not required.
 * Otherwise `R2_ACCOUNT_ID` is required and the Cloudflare R2 URL is derived
 * from it downstream in {@link buildS3Config}.
 */
export function resolveR2Env(env: Record<string, string | undefined>): R2Settings {
  for (const name of REQUIRED_VARS) {
    if (!env[name]) {
      throw new Error(`missing required env var: ${name}`);
    }
  }
  const base = {
    bucket: env.R2_BUCKET as string,
    accessKeyId: env.R2_ACCESS_KEY_ID as string,
    secretAccessKey: env.R2_SECRET_ACCESS_KEY as string,
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
 * Build the singleton {@link R2ArtifactStore} from the environment. The S3 client
 * is constructed ONCE here (it pools connections internally) and shared across
 * every stage in the worker process.
 */
/* v8 ignore start -- thin glue: real S3Client construction, exercised by integration not unit tests */
export function buildR2ArtifactStore(
  env: Record<string, string | undefined> = process.env,
): R2ArtifactStore {
  const settings = resolveR2Env(env);
  const s3Client = new S3Client(buildS3Config(settings));
  return new R2ArtifactStore({ bucket: settings.bucket, s3Client });
}
/* v8 ignore stop */
