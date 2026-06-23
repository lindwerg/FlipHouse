import type { IngestJobData } from '@fliphouse/shared';
import { INGEST_QUEUE_NAME } from '@fliphouse/shared';
import type { ConnectionOptions } from 'bullmq';
import { Queue } from 'bullmq';
import { Env } from '@/libs/Env';

// Server-side URL-ingestion producer. The dashboard POSTs a pasted video link to
// /api/uploads/ingest; this enqueues ONE lightweight `ingest` BullMQ job carrying
// the URL + the server-trusted ownerId. The worker (yt-dlp + ffmpeg + R2 creds)
// does the heavy download → R2 source object → ledger claim → render-flow enqueue,
// so the web tier never downloads bytes (no yt-dlp/ffmpeg, no long serverless
// timeout). The browser File path stays on tus; only links route through here.

/** The dedup key BullMQ uses so a re-submitted URL by the same owner is a no-op. */
function ingestJobId(data: IngestJobData): string {
  // A stable id per (owner, url) keeps a double-click / rapid re-submit from
  // enqueuing two downloads of the same link; the worker's content-hash claim is
  // the durable authority, this is just the cheap producer-side guard.
  return `ingest-${data.ownerId}-${encodeURIComponent(data.url)}`;
}

/**
 * BullMQ connection OPTIONS (not a constructed ioredis instance) from the web
 * Redis URL. Passing options lets BullMQ own its connection and sidesteps the
 * duplicate-ioredis type clash (bullmq pins its own ioredis copy) — mirroring the
 * worker's `redisConnectionFromUrl` seam. `maxRetriesPerRequest: null` is
 * mandatory for the blocking BullMQ connection; `rediss:` enables TLS.
 */
function ingestConnection(): ConnectionOptions {
  const parsed = new URL(Env.REDIS_PRIVATE_URL);
  return {
    host: parsed.hostname,
    port: parsed.port ? Number(parsed.port) : 6379,
    maxRetriesPerRequest: null,
    ...(parsed.username ? { username: decodeURIComponent(parsed.username) } : {}),
    ...(parsed.password ? { password: decodeURIComponent(parsed.password) } : {}),
    ...(parsed.protocol === 'rediss:' ? { tls: {} } : {}),
  };
}

/** Lazily-built singleton `ingest` Queue over the shared web Redis connection. */
let ingestQueue: Queue | null = null;

function getIngestQueue(): Queue {
  ingestQueue ??= new Queue(INGEST_QUEUE_NAME, { connection: ingestConnection() });
  return ingestQueue;
}

export interface EnqueueIngestDeps {
  readonly queue: Pick<Queue, 'add'>;
}

/**
 * Enqueue an ingest job for `data`. The `jobId` makes a rapid re-submit of the
 * same (owner, url) idempotent at the producer. The queue is injectable so the
 * route is unit-tested with no Redis.
 */
export async function enqueueIngest(
  data: IngestJobData,
  deps: EnqueueIngestDeps = { queue: getIngestQueue() },
): Promise<void> {
  await deps.queue.add(INGEST_QUEUE_NAME, data, {
    jobId: ingestJobId(data),
    removeOnComplete: { age: 3600, count: 1000 },
    removeOnFail: { age: 86_400 },
  });
}
