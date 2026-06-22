// Pure SSE framing + resume logic for the upload-progress stream (P2.3). Kept
// free of any ReadableStream / timer / request.signal I/O so it is unit-tested
// at 100%; the route wires these into the heavy stream behind a v8-ignore seam.

export interface SseFrame {
  readonly id: number;
  readonly event: string;
  readonly data: unknown;
}

/**
 * Serialises one SSE frame. The `id:` is the monotonic `statusOrdinal` (NEVER a
 * wall-clock value) so a reconnecting client's `Last-Event-ID` is comparable
 * forward-only. Data is JSON-encoded on a single `data:` line. Terminated by the
 * blank line the SSE wire format requires.
 */
export function buildSseFrame(frame: SseFrame): string {
  return `id: ${frame.id}\nevent: ${frame.event}\ndata: ${JSON.stringify(frame.data)}\n\n`;
}

/**
 * Forward-only resume edge: should the stream emit the current row given the
 * client's `Last-Event-ID` header? Emits only when the current ordinal is
 * strictly greater than what the client already saw, so a reconnect never
 * replays an already-delivered stage. A missing/blank/non-numeric header is
 * treated as "client has seen nothing" (-1) → the current state is always sent.
 */
export function sseResume(
  lastEventIdHeader: string | null | undefined,
  currentOrdinal: number,
): boolean {
  const parsed = Number.parseInt(lastEventIdHeader ?? '', 10);
  const lastSeen = Number.isNaN(parsed) ? -1 : parsed;
  return currentOrdinal > lastSeen;
}
