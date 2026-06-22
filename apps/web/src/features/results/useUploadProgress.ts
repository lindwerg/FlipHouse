'use client';

import { useEffect, useRef, useState } from 'react';
import type { ClipView } from './api-schemas';
import { clipsResponseSchema } from './api-schemas';
import { statusToProgress } from './upload-status';

// Reliability-first progress hook for the creator dashboard (P2.3). Polls the
// owner-scoped /clips snapshot (which carries the ledger `status` plus, once
// terminal-done, the ranked clips) on an interval, derives the % / Russian label
// / terminal flag from the pure statusToProgress, stops polling on any terminal
// status, and surfaces clips on done. The injected `fetch` + a real interval make
// it fully unit-testable with fake timers — no EventSource, no network. (The SSE
// /progress route is the live-push optimisation over the same data; this poller
// is the deterministic baseline the UI binds to.)

const POLL_INTERVAL_MS = 2000;

export type ProgressPhase = 'loading' | 'processing' | 'done' | 'failed' | 'duplicate';

export interface UploadProgress {
  phase: ProgressPhase;
  percent: number;
  phaseLabel: string;
  error: string | null;
  clips: readonly ClipView[];
}

export interface UseUploadProgressDeps {
  fetch?: typeof fetch;
  intervalMs?: number;
}

const INITIAL: UploadProgress = {
  phase: 'loading',
  percent: 0,
  phaseLabel: 'Загружаем статус',
  error: null,
  clips: [],
};

const GENERIC_ERROR = 'Не удалось получить статус обработки';

function phaseFor(status: string, isTerminal: boolean): ProgressPhase {
  if (!isTerminal) {
    return 'processing';
  }
  if (status === 'failed') {
    return 'failed';
  }
  if (status === 'duplicate') {
    return 'duplicate';
  }
  return 'done';
}

/**
 * Tracks an upload's processing progress by content hash. Passing `null` keeps
 * the hook idle (no polling) — used before an upload's hash is known. Polling
 * clears on unmount, on reaching a terminal status, and when the hash changes.
 */
export function useUploadProgress(
  contentHash: string | null,
  deps: UseUploadProgressDeps = {},
): UploadProgress {
  const [state, setState] = useState<UploadProgress>(INITIAL);
  /* v8 ignore next 3 -- default browser deps (real fetch + poll cadence); the
     logic is unit-tested with both injected. `.bind` is load-bearing: a bare
     `globalThis.fetch` reference called later throws "Illegal invocation" in the
     browser (fetch requires this===window), so the /clips poll would silently
     never fire — the request never leaves the page. */
  const fetchImpl = deps.fetch ?? globalThis.fetch.bind(globalThis);
  const intervalMs = deps.intervalMs ?? POLL_INTERVAL_MS;
  // Keep the latest fetch in a ref so changing it does not re-arm the interval.
  const fetchRef = useRef(fetchImpl);
  fetchRef.current = fetchImpl;

  useEffect(() => {
    if (contentHash === null) {
      setState(INITIAL);
      return;
    }

    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | undefined;
    setState(INITIAL);

    const stop = (): void => {
      if (timer) {
        clearInterval(timer);
        timer = undefined;
      }
    };

    const tick = async (): Promise<void> => {
      try {
        const res = await fetchRef.current(`/api/uploads/${contentHash}/clips`, {
          cache: 'no-store',
        });
        if (cancelled) {
          return;
        }
        if (!res.ok) {
          throw new Error(`status ${res.status}`);
        }
        const body = clipsResponseSchema.parse(await res.json());
        /* v8 ignore next 3 -- race guard: unmount between the fetch and json
           awaits; the fetch-await guard above is unit-tested. */
        if (cancelled) {
          return;
        }
        const progress = statusToProgress(body.status);
        const phase = phaseFor(body.status, progress.isTerminal);
        setState({
          phase,
          percent: progress.percent,
          phaseLabel: progress.label,
          error: phase === 'failed' ? progress.label : null,
          clips: body.clips,
        });
        if (progress.isTerminal) {
          stop();
        }
      } catch (caught) {
        if (cancelled) {
          return;
        }
        setState((prev) => ({
          ...prev,
          error: caught instanceof Error ? caught.message : GENERIC_ERROR,
        }));
      }
    };

    void tick();
    timer = setInterval(() => void tick(), intervalMs);

    return () => {
      cancelled = true;
      stop();
    };
  }, [contentHash, intervalMs]);

  return state;
}
