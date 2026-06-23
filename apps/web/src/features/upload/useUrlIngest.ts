'use client';

import { useCallback, useState } from 'react';
import * as z from 'zod';

// Drives the pasted-link path of the creator upload surface: POST the URL to
// /api/uploads/ingest, which enqueues a server-side yt-dlp download into the SAME
// render pipeline a file upload feeds. Unlike the file path (browser hashes +
// streams the bytes), the browser here only hands off the URL — the download is
// async on the worker — so this hook tracks a small submit→queued/error machine,
// NOT a byte-progress bar. Every network boundary is injectable so the machine is
// unit-tested with no fetch.

export type IngestStatus = 'idle' | 'submitting' | 'queued' | 'error';

const GENERIC_ERROR = 'Не удалось принять ссылку. Попробуйте ещё раз.';

/** Shape returned by POST /api/uploads/ingest on success — validated at the boundary. */
const ingestResponseSchema = z.object({ status: z.literal('queued') });

/** Error envelope the route returns on a 4xx/5xx — validated before surfacing. */
const ingestErrorSchema = z.object({ error: z.string().min(1) });

export type SubmitUrl = (url: string) => Promise<void>;

export interface UseUrlIngest {
  status: IngestStatus;
  error: string | null;
  submit: SubmitUrl;
}

/* v8 ignore start -- default browser dep: a real fetch. Covered by E2E; the hook
   logic is unit-tested with an injected postUrl. */
const defaultPostUrl: SubmitUrl = async (url: string) => {
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
};
/* v8 ignore stop */

function toMessage(error: unknown): string {
  return error instanceof Error && error.message.length > 0 ? error.message : GENERIC_ERROR;
}

export function useUrlIngest(postUrl: SubmitUrl = defaultPostUrl): UseUrlIngest {
  const [status, setStatus] = useState<IngestStatus>('idle');
  const [error, setError] = useState<string | null>(null);

  const submit = useCallback<SubmitUrl>(
    async (url: string): Promise<void> => {
      setError(null);
      setStatus('submitting');
      try {
        await postUrl(url);
        setStatus('queued');
      } catch (caught) {
        setError(toMessage(caught));
        setStatus('error');
      }
    },
    [postUrl],
  );

  return { status, error, submit };
}
