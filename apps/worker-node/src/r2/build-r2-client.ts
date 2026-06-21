import { S3Client } from '@aws-sdk/client-s3';

import { R2ArtifactStore, buildS3Config } from './artifact-store.js';

/** R2 connection settings, validated out of the process environment. */
export interface R2Settings {
  readonly accountId: string;
  readonly bucket: string;
  readonly accessKeyId: string;
  readonly secretAccessKey: string;
}

const REQUIRED_VARS = [
  'R2_ACCOUNT_ID',
  'R2_BUCKET',
  'R2_ACCESS_KEY_ID',
  'R2_SECRET_ACCESS_KEY',
] as const;

/**
 * Validate R2 env vars into typed settings, failing fast (at process start, on
 * Railway) with a message naming the first missing var. An empty string counts
 * as missing — a blank secret is never a valid credential.
 */
export function resolveR2Env(env: Record<string, string | undefined>): R2Settings {
  for (const name of REQUIRED_VARS) {
    if (!env[name]) {
      throw new Error(`missing required env var: ${name}`);
    }
  }
  return {
    accountId: env.R2_ACCOUNT_ID as string,
    bucket: env.R2_BUCKET as string,
    accessKeyId: env.R2_ACCESS_KEY_ID as string,
    secretAccessKey: env.R2_SECRET_ACCESS_KEY as string,
  };
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
