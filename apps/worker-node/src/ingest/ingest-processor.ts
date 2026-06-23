import { ingestJobDataSchema } from '@fliphouse/shared';
import type { Job, Processor } from 'bullmq';

import { runIngest } from './ingest-handler.js';
import type { IngestDeps, IngestOutcome } from './ingest-handler.js';
import { IngestDownloadError } from './ytdlp-download.js';

/**
 * BullMQ {@link Processor} for the `ingest` queue. Validates the job payload
 * (url + server-trusted ownerId), runs the ingest end-to-end, and on a LOUD
 * classified download failure records a durable failure row (so the dashboard /
 * an operator can see WHY a URL did not ingest) before rethrowing so BullMQ marks
 * the job failed. A non-download error (R2/pg/Redis) rethrows untouched — it is a
 * genuine infra failure BullMQ should retry.
 */

/** Sink for a failed ingest, so the loud error survives Redis eviction (dead-letter). */
export interface IngestFailureSink {
  recordIngestFailure(url: string, ownerId: string, kind: string, message: string): Promise<void>;
}

export interface IngestProcessorDeps extends IngestFailureSink {
  readonly ingest: IngestDeps;
}

export function makeIngestProcessor(deps: IngestProcessorDeps): Processor<unknown, IngestOutcome> {
  return async (job: Job): Promise<IngestOutcome> => {
    const data = ingestJobDataSchema.parse(job.data);
    try {
      return await runIngest({ url: data.url, ownerId: data.ownerId }, deps.ingest);
    } catch (err: unknown) {
      // A classified download failure is the user's problem (geo/IP/private/age):
      // record it durably with its kind + Russian user message, then rethrow so the
      // BullMQ job is FAILED (not silently swallowed).
      if (err instanceof IngestDownloadError) {
        await deps.recordIngestFailure(data.url, data.ownerId, err.kind, err.userMessage);
      }
      throw err;
    }
  };
}
