import { z } from 'zod';

/**
 * Server-side URL ingestion contract (shared by the web producer and the
 * worker-node consumer). A pasted YouTube/Vimeo/direct-mp4 link cannot be
 * uploaded by the browser the way a File is (the bytes live on a third-party
 * host), so the web tier enqueues ONE lightweight `ingest` job carrying the URL;
 * the worker (which has yt-dlp + ffmpeg + R2 creds) does the heavy download,
 * content-hashes the bytes, writes the R2 source object, then claims the ledger
 * and enqueues the SAME render flow a file upload's tusd post-finish hook does.
 *
 * `ingest` is deliberately NOT a pipeline {@link Stage}: it is a PRE-stage that
 * PRODUCES the content-hash + source object the DAG starts from, so it lives on
 * its own queue rather than inside the transcode→…→publish tree.
 */

/** The BullMQ queue the ingest job runs on (its own lane, not a DAG stage queue). */
export const INGEST_QUEUE_NAME = 'ingest';

/**
 * Hosts/extensions yt-dlp can resolve. Mirrors the web `isVideoUrl` predicate so
 * the producer and consumer agree on what a "video URL" is — re-validated on the
 * worker side as defence in depth (never trust the job payload's URL blindly).
 */
const VIDEO_HOSTS = [
  /(^|\.)youtube\.com$/,
  /(^|\.)youtu\.be$/,
  /(^|\.)vimeo\.com$/,
  /(^|\.)dailymotion\.com$/,
  /(^|\.)twitch\.tv$/,
];

const VIDEO_FILE = /\.(mp4|mov|webm|m4v)$/i;

/** True when `value` is an http(s) URL on a known video host OR a direct video file. */
export function isIngestableUrl(value: string): boolean {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return false;
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    return false;
  }
  if (VIDEO_HOSTS.some((host) => host.test(url.hostname))) {
    return true;
  }
  return VIDEO_FILE.test(url.pathname);
}

/**
 * Job payload the web route attaches to every ingest job. `ownerId` is the
 * server-trusted Clerk userId (never client-supplied), mirroring the upload
 * grant's ownership contract; `url` is re-validated as an ingestable video URL.
 */
export const ingestJobDataSchema = z.object({
  url: z.string().url().refine(isIngestableUrl, { message: 'not an ingestable video URL' }),
  ownerId: z.string().min(1),
});

export type IngestJobData = z.infer<typeof ingestJobDataSchema>;
