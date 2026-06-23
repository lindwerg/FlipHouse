import { execFile } from 'node:child_process';

import { assertPublicUrl } from './ssrf-guard.js';
import type { LookupFn } from './ssrf-guard.js';

/**
 * yt-dlp download seam — the single subprocess boundary of URL ingestion.
 *
 * yt-dlp (Unlicense / public-domain → commercial-safe) resolves a pasted video
 * URL (YouTube, Vimeo, Dailymotion, Twitch, OR a direct .mp4/.mov/.webm) to a
 * single best-quality MP4 on local disk. The download is intentionally ROBUST:
 * a format-fallback chain (prefer an mp4 muxed/merged stream, fall back to the
 * best available), bounded retries on transient 5xx/429, fragment retries for
 * segmented hosts, and a hard wall-clock timeout so a wedged download cannot
 * hold the worker lock.
 *
 * CAVEAT (memory: yt-dlp blocked via googlevideo): YouTube frequently blocks
 * datacenter IPs (the Railway egress is one). When that happens yt-dlp exits
 * non-zero with a recognizable message; {@link classifyYtdlpError} maps it to a
 * LOUD, user-facing {@link IngestDownloadError} so the dashboard can tell the
 * creator exactly why (geo/IP-block / age / private / unavailable) instead of a
 * generic 500. Direct-mp4 and Vimeo do not go through googlevideo and stay
 * reliable even when YouTube is flaky.
 */

/** Categories of download failure, each mapped to a distinct user-facing message. */
export type IngestFailureKind =
  | 'ip-blocked'
  | 'unavailable'
  | 'private'
  | 'age-restricted'
  | 'geo-restricted'
  | 'network'
  | 'unknown';

/** A classified, loud download failure carrying both a kind and a Russian message. */
export class IngestDownloadError extends Error {
  readonly kind: IngestFailureKind;
  /** Russian, user-facing copy the dashboard surfaces verbatim. */
  readonly userMessage: string;

  constructor(kind: IngestFailureKind, userMessage: string, detail: string) {
    super(`${kind}: ${detail}`);
    this.name = 'IngestDownloadError';
    this.kind = kind;
    this.userMessage = userMessage;
  }
}

/** Russian user-facing copy per failure kind (the dashboard shows these verbatim). */
const USER_MESSAGE: Record<IngestFailureKind, string> = {
  'ip-blocked':
    'YouTube заблокировал загрузку с нашего сервера. Скачайте видео и загрузите файлом, или пришлите прямую ссылку (.mp4) либо Vimeo.',
  unavailable: 'Видео недоступно по этой ссылке. Проверьте ссылку и попробуйте снова.',
  private: 'Это видео приватное — мы не можем его скачать. Сделайте его публичным или загрузите файлом.',
  'age-restricted':
    'Видео с возрастным ограничением скачать нельзя. Загрузите его файлом или пришлите другую ссылку.',
  'geo-restricted':
    'Видео недоступно в нашем регионе. Загрузите его файлом или пришлите прямую ссылку (.mp4).',
  network: 'Не удалось скачать видео по сети. Попробуйте ещё раз через минуту.',
  unknown: 'Не удалось скачать видео по ссылке. Попробуйте загрузить файлом.',
};

/**
 * Classify a raw yt-dlp stderr blob into an {@link IngestFailureKind}. Order is
 * load-bearing: the most specific signals (IP block, age, geo, private) are
 * matched before the generic "unavailable"/"network" buckets so the user gets the
 * most actionable message. Pure + exported so every branch is unit-tested.
 */
export function classifyYtdlpError(stderr: string): IngestFailureKind {
  const text = stderr.toLowerCase();
  // YouTube's datacenter-IP wall (googlevideo) — the documented memory caveat.
  if (
    text.includes('sign in to confirm') ||
    text.includes("confirm you're not a bot") ||
    text.includes('http error 429') ||
    text.includes('this content isn’t available') ||
    text.includes('failed to extract any player response')
  ) {
    return 'ip-blocked';
  }
  if (text.includes('age') && (text.includes('restrict') || text.includes('confirm your age'))) {
    return 'age-restricted';
  }
  if (text.includes('private video') || text.includes('this video is private')) {
    return 'private';
  }
  if (
    text.includes('not available in your country') ||
    text.includes('geo') ||
    text.includes('blocked it in your country')
  ) {
    return 'geo-restricted';
  }
  if (
    text.includes('video unavailable') ||
    text.includes('removed') ||
    text.includes('does not exist') ||
    text.includes('http error 404') ||
    text.includes('unsupported url')
  ) {
    return 'unavailable';
  }
  if (
    text.includes('unable to download') ||
    text.includes('connection') ||
    text.includes('timed out') ||
    text.includes('temporary failure')
  ) {
    return 'network';
  }
  return 'unknown';
}

/** Build the loud, classified error for a failed yt-dlp invocation. */
export function ingestErrorFromStderr(stderr: string): IngestDownloadError {
  const kind = classifyYtdlpError(stderr);
  return new IngestDownloadError(kind, USER_MESSAGE[kind], stderr.trim().slice(0, 500) || 'no stderr');
}

/**
 * yt-dlp CLI arguments for a robust best-quality MP4 download to `outPath`.
 *
 * - `-f`: prefer a pre-muxed/merged H.264+AAC mp4 ≤1080p, then any best mp4, then
 *   the best of anything — so a host with no mp4 still yields a file (we transcode
 *   to a proxy downstream anyway).
 * - `--merge-output-format mp4`: when separate A/V streams are picked, mux to mp4.
 * - `--retries` / `--fragment-retries`: ride out transient 5xx/429 and dropped
 *   segments on chunked hosts.
 * - `--socket-timeout`: per-connection ceiling (the whole-process ceiling is the
 *   spawn timeout below).
 * - `--no-playlist`: a playlist URL ingests only the single video, never N videos.
 * - `--max-filesize`: hard size ceiling so a hostile/huge URL cannot be an
 *   unbounded-download DoS / R2-cost vector (the same field that drives SSRF).
 * - `--no-progress` / `--newline`: machine-friendly, non-TTY output.
 */
export function ytdlpArgs(url: string, outPath: string): string[] {
  return [
    '-f',
    'best[ext=mp4][height<=1080]/best[ext=mp4]/best',
    '--merge-output-format',
    'mp4',
    '--no-playlist',
    '--max-filesize',
    MAX_DOWNLOAD_FILESIZE,
    '--retries',
    '5',
    '--fragment-retries',
    '5',
    '--socket-timeout',
    '30',
    '--no-progress',
    '--newline',
    '--no-warnings',
    '-o',
    outPath,
    url,
  ];
}

/** Hard wall-clock ceiling for one download — below the worker lock (30 min). */
export const DOWNLOAD_TIMEOUT_MS = 20 * 60 * 1000;

/**
 * Hard per-download size ceiling passed to yt-dlp (`--max-filesize`). A creator's
 * source video is well under this; the cap exists so a hostile or accidental URL
 * cannot become an unbounded download (worker disk / R2 cost / DoS). yt-dlp aborts
 * the download once the declared/streamed size crosses it.
 */
export const MAX_DOWNLOAD_FILESIZE = '4G';

/** The execFile-shaped seam, injectable so the handler is unit-tested with no real yt-dlp. */
export type ExecFileFn = (
  command: string,
  args: readonly string[],
  options: { timeout: number; maxBuffer: number },
) => Promise<{ stdout: string; stderr: string }>;

/* v8 ignore start -- real subprocess I/O; covered by the injected execFile seam */
const defaultExecFile: ExecFileFn = (command, args, options) =>
  new Promise((resolve, reject) => {
    execFile(command, [...args], options, (err, stdout, stderr) => {
      if (err) {
        // Attach the captured stderr so the classifier sees yt-dlp's real message.
        reject(Object.assign(err, { stderr: stderr || err.message }));
        return;
      }
      resolve({ stdout, stderr });
    });
  });
/* v8 ignore stop */

/** yt-dlp binary path (overridable for a vendored install); defaults to PATH lookup. */
export const YTDLP_BIN = process.env.YTDLP_BIN ?? 'yt-dlp';

/** Cap on captured stderr/stdout so a chatty failure cannot blow up worker memory. */
const MAX_OUTPUT_BYTES = 4 * 1024 * 1024;

export interface DownloadDeps {
  readonly execFile?: ExecFileFn;
  readonly bin?: string;
  readonly timeoutMs?: number;
  /** DNS-resolution seam for the SSRF guard, injectable for unit tests. */
  readonly lookup?: LookupFn;
}

/**
 * Download `url` to `outPath` via yt-dlp. FIRST asserts the URL host is public
 * (literal + DNS-resolved SSRF guard) so an internal/metadata target is rejected
 * BEFORE any subprocess spawns, then resolves on success or throws a loud,
 * classified {@link IngestDownloadError} on any non-zero exit (the kind drives the
 * user-facing dashboard message). Never resolves on a partial/failed download.
 */
export async function downloadVideo(
  url: string,
  outPath: string,
  deps: DownloadDeps = {},
): Promise<void> {
  // SSRF pre-flight: reject private/loopback/link-local/metadata hosts (and hosts
  // that DNS-resolve to one) before yt-dlp ever opens a socket. Throws a loud
  // IngestDownloadError that propagates exactly like a download failure.
  await assertPublicUrl(url, deps.lookup);

  const run = deps.execFile ?? defaultExecFile;
  const bin = deps.bin ?? YTDLP_BIN;
  const timeout = deps.timeoutMs ?? DOWNLOAD_TIMEOUT_MS;
  try {
    await run(bin, ytdlpArgs(url, outPath), { timeout, maxBuffer: MAX_OUTPUT_BYTES });
  } catch (err: unknown) {
    const stderr =
      err && typeof err === 'object' && 'stderr' in err && typeof err.stderr === 'string'
        ? err.stderr
        : err instanceof Error
          ? err.message
          : String(err);
    throw ingestErrorFromStderr(stderr);
  }
}
