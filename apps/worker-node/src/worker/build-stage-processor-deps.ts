import { randomUUID } from 'node:crypto';

import { GetObjectCommand, S3Client } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';
import { finishUpload, upsertClips } from '@fliphouse/db';
import type { Db } from '@fliphouse/db';
import { Redis } from 'ioredis';

import { resolveAsrEnv, webhookCallbackUrl } from '../gpu/asr-env.js';
import { gpuSubmit } from '../gpu/gpu-submit.js';
import { runPythonStage } from '../python/spawn.js';
import { buildS3Config } from '../r2/artifact-store.js';
import { buildR2ArtifactStore, resolveR2Env } from '../r2/build-r2-client.js';
import type { AsrLaneDeps } from '../stages/execute-asr.js';
import type { StageProcessorDeps } from '../stages/stage-processor.js';
import { createRedisParker } from '../state/park.js';

/** Presigned-GET lifetime for the asr audio the GPU fetches (24h — covers a long queue). */
export const PRESIGN_TTL_SEC = 86_400;

/**
 * Wire the production {@link StageProcessorDeps} from an injected Db handle + env:
 * the R2 artifact store (sentinels + markers + manifest read), the Python
 * subprocess runner, the publish DB writers, AND the ASR submit-and-park lane.
 *
 * BOOT-ASSERT: {@link resolveAsrEnv} throws an `AsrEnvError` here (at process
 * start, before any job is pulled) if `GPU_ASR_ENABLED==="true"` and any of
 * `GIGAAM_ENDPOINT`/`GIGAAM_WEBHOOK_SECRET`/`WEBHOOK_PUBLIC_URL` is missing — so
 * a misconfigured park lane fails the DEPLOY, not every claimed asr job.
 *
 * The Db/Pool lifecycle is owned by the caller ({@link runWorkers}); the ioredis
 * + presigner S3 client are constructed here behind the v8-ignored real seams.
 */
/* v8 ignore start -- thin glue: real S3/ioredis/presigner construction, exercised by integration not unit tests */
export function buildStageProcessorDeps(
  db: Db,
  env: Record<string, string | undefined> = process.env,
): StageProcessorDeps {
  const r2 = buildR2ArtifactStore(env);
  const asrEnv = resolveAsrEnv(env);
  return {
    r2,
    runStage: (request, signal) => runPythonStage(request, signal ? { signal } : {}),
    publish: {
      readJson: (key) => r2.getJson(key),
      copyObject: (fromKey, toKey) => r2.copyObject(fromKey, toKey),
      upsertClips: (contentHash, rows) => upsertClips(db, contentHash, rows),
      finishUpload: (contentHash, input) => finishUpload(db, contentHash, input),
    },
    asr: buildAsrLaneDeps(asrEnv, env),
  };
}

/** Construct the ASR park-lane deps (real ioredis + presigner) from the resolved env. */
function buildAsrLaneDeps(
  asrEnv: ReturnType<typeof resolveAsrEnv>,
  env: Record<string, string | undefined>,
): AsrLaneDeps {
  // Disabled → an inert lane: the asr stage runs inline (executeStage). The
  // endpoint/url placeholders are never read when gpuParkEnabled is false.
  if (!asrEnv.enabled) {
    return {
      gpuParkEnabled: false,
      redis: { set: async () => 'OK', zadd: async () => 0 },
      gpuSubmit,
      presignAudio: async () => '',
      newRequestId: randomUUID,
      nowMs: Date.now,
      gigaamEndpoint: '',
      webhookCallbackUrl: '',
    };
  }

  const settings = resolveR2Env(env);
  const presignClient = new S3Client(buildS3Config(settings));
  const redisUrl = env.REDIS_URL ?? '';
  const redis = new Redis(redisUrl, { maxRetriesPerRequest: null });
  const parker = createRedisParker(redis);

  const presignAudio = (key: string): Promise<string> =>
    getSignedUrl(presignClient, new GetObjectCommand({ Bucket: settings.bucket, Key: key }), {
      expiresIn: PRESIGN_TTL_SEC,
    });

  return {
    gpuParkEnabled: true,
    redis: parker,
    gpuSubmit,
    presignAudio,
    newRequestId: randomUUID,
    nowMs: Date.now,
    gigaamEndpoint: asrEnv.endpoint,
    webhookCallbackUrl: webhookCallbackUrl(asrEnv.webhookPublicUrl),
  };
}
/* v8 ignore stop */
