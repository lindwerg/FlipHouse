'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import * as z from 'zod';

// Drives the pasted-link path of the creator upload surface: POST the URL to
// /api/uploads/ingest, which enqueues a server-side yt-dlp download into the SAME
// render pipeline a file upload feeds. Unlike the file path (browser hashes +
// streams the bytes), the browser here only hands off the URL — the download is
// async on the worker — so this hook tracks a small submit→queued/error machine,
// NOT a byte-progress bar.
//
// CRITICAL (silent-hang fix): the download's real failures (YouTube IP-block /
// private / geo) happen LATER on the worker, long after the 202. The submit
// returns a deterministic `ingestId`; this hook then POLLS GET
// /api/uploads/ingest/[ingestId], and when the worker has recorded a classified
// failure it surfaces that LOUD Russian message as `error` — so a failed link is
// never a silent "принято в работу" with nothing after it. Every network +
// timer boundary is injectable so the machine is unit-tested with no fetch/clock.

export type IngestStatus = 'idle' | 'submitting' | 'queued' | 'error';

const GENERIC_ERROR = 'Не удалось принять ссылку. Попробуйте ещё раз.';

/** Shape returned by POST /api/uploads/ingest on success — validated at the boundary. */
const ingestResponseSchema = z.object({
  status: z.literal('queued'),
  ingestId: z.string().min(1),
});

/** Error envelope the route returns on a 4xx/5xx — validated before surfacing. */
const ingestErrorSchema = z.object({ error: z.string().min(1) });

/** Shape returned by GET /api/uploads/ingest/[ingestId] — the async download outcome. */
const ingestStatusSchema = z.union([
  z.object({ status: z.literal('pending') }),
  z.object({ status: z.literal('failed'), error: z.string().min(1) }),
]);

/** How often the async download outcome is polled, and the upper bound on polls. */
export const INGEST_POLL_INTERVAL_MS = 3000;
export const INGEST_MAX_POLLS = 120; // ~6 min — above the worker download timeout.

/** The submit seam: POST the URL, returning the deterministic ingest key to poll. */
export type SubmitUrlRequest = (url: string) => Promise<string>;
/** The poll seam: read the async download outcome for an ingest key. */
export type PollIngestStatus = (ingestId: string) => Promise<IngestPollResult>;
/** The result of one async-download poll. */
export type IngestPollResult =
  | { readonly status: 'pending' }
  | { readonly status: 'failed'; readonly error: string };

export type SubmitUrl = (url: string) => Promise<void>;

export interface UseUrlIngest {
  status: IngestStatus;
  error: string | null;
  submit: SubmitUrl;
}

/* v8 ignore start -- default browser deps: real fetch. Covered by E2E; the hook
   logic is unit-tested with injected seams. */
const defaultSubmitUrl: SubmitUrlRequest = async (url: string) => {
  const res = await fetch('/api/uploads/ingest', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const parsed = ingestErrorSchema.safeParse(body);
    throw new Error(parsed.success ? parsed.data.error : GENERIC_ERROR);
  }
  const ok = ingestResponseSchema.safeParse(await res.json().catch(() => null));
  if (!ok.success) {
    throw new Error(GENERIC_ERROR);
  }
  return ok.data.ingestId;
};

const defaultPollStatus: PollIngestStatus = async (ingestId: string) => {
  const res = await fetch(`/api/uploads/ingest/${encodeURIComponent(ingestId)}`);
  if (!res.ok) {
    return { status: 'pending' };
  }
  const parsed = ingestStatusSchema.safeParse(await res.json().catch(() => null));
  if (!parsed.success) {
    return { status: 'pending' };
  }
  return parsed.data.status === 'failed'
    ? { status: 'failed', error: parsed.data.error }
    : { status: 'pending' };
};
/* v8 ignore stop */

function toMessage(error: unknown): string {
  return error instanceof Error && error.message.length > 0 ? error.message : GENERIC_ERROR;
}

export interface UseUrlIngestDeps {
  readonly submitUrl?: SubmitUrlRequest;
  readonly pollStatus?: PollIngestStatus;
  /** Delay seam (defaults to setTimeout), injectable so the poll loop is clock-free in tests. */
  readonly delay?: (ms: number) => Promise<void>;
}

/* v8 ignore start -- default browser timer seam; the poll loop is tested with an injected delay. */
const defaultDelay = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));
/* v8 ignore stop */

export function useUrlIngest(deps: UseUrlIngestDeps = {}): UseUrlIngest {
  const submitUrl = deps.submitUrl ?? defaultSubmitUrl;
  const pollStatus = deps.pollStatus ?? defaultPollStatus;
  const delay = deps.delay ?? defaultDelay;

  const [status, setStatus] = useState<IngestStatus>('idle');
  const [error, setError] = useState<string | null>(null);

  // Each submit gets a fresh token; an in-flight poll loop from a PRIOR submit
  // checks the token and aborts, so a stale failure can never clobber a new submit.
  const runRef = useRef(0);

  // Stop any in-flight poll loop on unmount (no setState after teardown).
  useEffect(() => () => {
    runRef.current += 1;
  }, []);

  // Poll the async download outcome in the BACKGROUND (not awaited by `submit`, so
  // the caller's await resolves at `queued`). A recorded failure flips to a LOUD
  // error; `pending` keeps polling up to the bound (then we stop — the download
  // either succeeded, surfacing in "Мои клипы", or exceeded our poll window). The
  // `run` token aborts a stale loop the moment a newer submit / unmount supersedes it.
  const pollUntilOutcome = useCallback(
    async (ingestId: string, run: number): Promise<void> => {
      for (let attempt = 0; attempt < INGEST_MAX_POLLS; attempt += 1) {
        await delay(INGEST_POLL_INTERVAL_MS);
        if (runRef.current !== run) {
          return;
        }
        let result: IngestPollResult;
        try {
          result = await pollStatus(ingestId);
        } catch {
          // A transient poll error is not a download failure — keep polling.
          continue;
        }
        if (runRef.current !== run) {
          return;
        }
        if (result.status === 'failed') {
          setError(result.error);
          setStatus('error');
          return;
        }
      }
    },
    [pollStatus, delay],
  );

  const submit = useCallback<SubmitUrl>(
    async (url: string): Promise<void> => {
      const run = (runRef.current += 1);
      setError(null);
      setStatus('submitting');

      let ingestId: string;
      try {
        ingestId = await submitUrl(url);
      } catch (caught) {
        if (runRef.current === run) {
          setError(toMessage(caught));
          setStatus('error');
        }
        return;
      }
      if (runRef.current !== run) {
        return;
      }
      setStatus('queued');
      // Fire-and-forget: the link is accepted; the async outcome surfaces later.
      void pollUntilOutcome(ingestId, run);
    },
    [submitUrl, pollUntilOutcome],
  );

  return { status, error, submit };
}
