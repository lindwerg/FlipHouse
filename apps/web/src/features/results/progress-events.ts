import type { UploadStatus } from '@fliphouse/db';
import type { ProgressResponse } from './api-schemas';
import { buildSseFrame } from './progress-stream';
import { statusOrdinal, statusToProgress } from './upload-status';

// Pure glue between a ledger status and one SSE wire frame (P2.3). Combines the
// status→progress mapping, the monotonic ordinal id and SSE framing into a
// single value so the /progress route's stream body stays a thin I/O shell.
// Unit-tested at 100%; no timers, no streams.

export interface ProgressEvent {
  readonly ordinal: number;
  readonly isTerminal: boolean;
  readonly payload: ProgressResponse;
  readonly frame: string;
}

/**
 * Builds the full progress event for a status: its monotonic ordinal (the SSE
 * `id:`), the JSON payload, the terminal flag, and the serialised SSE frame. A
 * terminal status uses the `done` event name (the client closes on it); an
 * in-flight status uses `progress`.
 */
export function buildProgressEvent(status: UploadStatus): ProgressEvent {
  const progress = statusToProgress(status);
  const ordinal = statusOrdinal(status);
  const payload: ProgressResponse = {
    status,
    percent: progress.percent,
    label: progress.label,
    isTerminal: progress.isTerminal,
  };
  const eventName = progress.isTerminal ? 'done' : 'progress';
  const frame = buildSseFrame({ id: ordinal, event: eventName, data: payload });
  return { ordinal, isTerminal: progress.isTerminal, payload, frame };
}
