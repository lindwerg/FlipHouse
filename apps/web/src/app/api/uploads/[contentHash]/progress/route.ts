import type { UploadStatus } from '@fliphouse/db';
import { auth } from '@clerk/nextjs/server';
import { listClipsForOwner } from '@fliphouse/db';
import { contentHashParamSchema } from '@/features/results/api-schemas';
import { buildProgressEvent } from '@/features/results/progress-events';
import { sseResume } from '@/features/results/progress-stream';
import { db } from '@/libs/DB';

// Live upload-progress stream (P2.3, SSE). Reliability-first design:
//   • The Response is returned IMMEDIATELY with the stream body — the polling
//     job is NEVER awaited before returning (avoids the Next SSE buffer bug).
//   • Source of truth is the owner-scoped ledger row, polled every 2s (idle
//     backoff to 4s). status→{percent,label} is the pure statusToProgress.
//   • Event `id:` is the monotonic statusOrdinal, never wall-clock; on reconnect
//     the client's Last-Event-ID gates a forward-only edge (pure sseResume).
//   • Heartbeat ': hb' every 12s keeps proxies from closing an idle stream.
//   • On a terminal status emit the event then close. request.signal abort and
//     any enqueue failure clear both intervals and close — no leaked timers.
// Auth: Clerk userId must own the ledger row (else 404), same as /clips.
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const POLL_INTERVAL_MS = 2000;
const IDLE_POLL_INTERVAL_MS = 4000;
const HEARTBEAT_INTERVAL_MS = 12000;
const HEARTBEAT_FRAME = ': hb\n\n';
// After this many unchanged polls, back off the poll cadence to ease DB load.
const IDLE_POLL_THRESHOLD = 5;

interface RouteContext {
  params: Promise<{ contentHash: string }>;
}

export async function GET(req: Request, context: RouteContext): Promise<Response> {
  const { userId } = await auth();
  if (!userId) {
    return Response.json({ error: 'unauthenticated' }, { status: 401 });
  }

  const { contentHash } = await context.params;
  const parsed = contentHashParamSchema.safeParse(contentHash);
  if (!parsed.success) {
    return Response.json({ error: 'invalid contentHash' }, { status: 400 });
  }

  // Ownership gate up front (single read): a missing/wrong-owner row → 404 before
  // we ever open a stream, so a forged hash never gets an event-stream Response.
  const owned = await listClipsForOwner(db, parsed.data, userId);
  if (!owned) {
    return Response.json({ error: 'not found' }, { status: 404 });
  }

  const lastEventId = req.headers.get('Last-Event-ID');
  const stream = createProgressStream(parsed.data, userId, lastEventId, req.signal, owned.status);

  return new Response(stream, {
    status: 200,
    headers: {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  });
}

/* v8 ignore start -- real-IO stream body: ReadableStream + setInterval polling +
   request.signal abort. The framing/resume/status math it delegates to
   (buildProgressEvent, sseResume, statusToProgress) is unit-tested at 100%; the
   stream wiring itself is exercised by E2E. */
function createProgressStream(
  contentHash: string,
  ownerId: string,
  lastEventIdHeader: string | null,
  signal: AbortSignal,
  seedStatus: UploadStatus,
): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();

  return new ReadableStream<Uint8Array>({
    start(controller) {
      let pollTimer: ReturnType<typeof setInterval> | undefined;
      let heartbeatTimer: ReturnType<typeof setInterval> | undefined;
      let closed = false;
      let lastOrdinal = -1;
      let unchangedPolls = 0;
      let currentPollMs = POLL_INTERVAL_MS;

      const cleanup = (): void => {
        if (closed) {
          return;
        }
        closed = true;
        if (pollTimer) {
          clearInterval(pollTimer);
        }
        if (heartbeatTimer) {
          clearInterval(heartbeatTimer);
        }
        signal.removeEventListener('abort', cleanup);
        try {
          controller.close();
        } catch {
          // already closed
        }
      };

      const safeEnqueue = (frame: string): boolean => {
        if (closed) {
          return false;
        }
        try {
          controller.enqueue(encoder.encode(frame));
          return true;
        } catch {
          cleanup();
          return false;
        }
      };

      const emitStatus = (status: UploadStatus): void => {
        const event = buildProgressEvent(status);
        // Forward-only: skip a stage the reconnecting client has already seen.
        const resumeAgainst = lastOrdinal >= 0 ? String(lastOrdinal) : lastEventIdHeader;
        if (!sseResume(resumeAgainst, event.ordinal)) {
          return;
        }
        lastOrdinal = event.ordinal;
        if (safeEnqueue(event.frame) && event.isTerminal) {
          cleanup();
        }
      };

      const poll = async (): Promise<void> => {
        if (closed) {
          return;
        }
        try {
          const owned = await listClipsForOwner(db, contentHash, ownerId);
          if (!owned) {
            cleanup();
            return;
          }
          const prevOrdinal = lastOrdinal;
          emitStatus(owned.status);
          if (lastOrdinal === prevOrdinal) {
            unchangedPolls += 1;
            if (unchangedPolls >= IDLE_POLL_THRESHOLD && currentPollMs !== IDLE_POLL_INTERVAL_MS) {
              currentPollMs = IDLE_POLL_INTERVAL_MS;
              if (pollTimer) {
                clearInterval(pollTimer);
              }
              pollTimer = setInterval(() => void poll(), currentPollMs);
            }
          } else {
            unchangedPolls = 0;
          }
        } catch {
          cleanup();
        }
      };

      if (signal.aborted) {
        cleanup();
        return;
      }
      signal.addEventListener('abort', cleanup);

      // Seed the current row immediately so a fresh (or reconnecting) client sees
      // state without waiting a full poll interval.
      emitStatus(seedStatus);
      if (closed) {
        return;
      }

      pollTimer = setInterval(() => void poll(), currentPollMs);
      heartbeatTimer = setInterval(() => safeEnqueue(HEARTBEAT_FRAME), HEARTBEAT_INTERVAL_MS);
    },
  });
}
/* v8 ignore stop */
