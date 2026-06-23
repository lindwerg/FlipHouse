import { mkdtempSync } from 'node:fs';
import { rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { claimUpload, recordFailure, setFlowJobId } from '@fliphouse/db';
import type { Db } from '@fliphouse/db';
import { flowJobId, ingestFailureKey } from '@fliphouse/shared';

import { enqueueFlow } from '../flow/flow-producer.js';
import type { FlowEnqueuer } from '../flow/flow-producer.js';
import type { R2ArtifactStore } from '../r2/artifact-store.js';

import { hashFile } from './hash-file.js';
import type { IngestDeps } from './ingest-handler.js';
import type { IngestProcessorDeps } from './ingest-processor.js';
import { downloadVideo } from './ytdlp-download.js';

/* v8 ignore start -- real yt-dlp + fs + R2 + pg/BullMQ wiring; exercised in integration, not unit tests */

/** Local filename for a download (the deterministic suffix lets ffmpeg probe it). */
const DOWNLOAD_NAME = 'source.mp4';

/** The stage label recorded for a durable ingest failure (dead-letter audit). */
const INGEST_STAGE = 'ingest';

/**
 * Bind the pure ingest handler + processor to production effects: yt-dlp download,
 * streamed file-hash, R2 file upload, the durable ledger claim, the shared
 * FlowProducer, and a per-job temp dir. The handler stays storage/queue-agnostic;
 * only this seam knows about yt-dlp, fs, R2, pg, and BullMQ.
 */
export function buildIngestDeps(
  db: Db,
  r2: R2ArtifactStore,
  producer: FlowEnqueuer,
): IngestProcessorDeps {
  const ingest: IngestDeps = {
    download: (url, localPath) => downloadVideo(url, localPath),
    hashFile: (localPath) => hashFile(localPath),
    putFile: (localPath, key, contentType) => r2.putFile(localPath, key, contentType),
    claimUpload: (input) => claimUpload(db, input),
    enqueueFlow: async (args) => {
      await enqueueFlow(producer, args);
    },
    markEnqueued: (contentHash) => setFlowJobId(db, contentHash, flowJobId(contentHash)),
    tempPath: () => join(mkdtempSync(join(tmpdir(), 'fh-ingest-')), DOWNLOAD_NAME),
    cleanup: async (localPath) => {
      // Remove the per-job temp DIR (parent of the file), never throwing on a
      // missing path so cleanup is a pure best-effort guard.
      await rm(join(localPath, '..'), { recursive: true, force: true });
    },
  };

  return {
    ingest,
    recordIngestFailure: (url, ownerId, kind, message) =>
      recordFailure(db, ingestFailureKey(url), INGEST_STAGE, kind, message, ownerId),
  };
}

/* v8 ignore stop */
