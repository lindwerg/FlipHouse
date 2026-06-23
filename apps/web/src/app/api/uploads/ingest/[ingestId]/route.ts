import { auth } from '@clerk/nextjs/server';
import { findIngestFailure } from '@fliphouse/db';
import * as z from 'zod';
import { db } from '@/libs/DB';

// Async ingest-status poll (P2). The submit route returns 202 immediately — the
// real download (and its YouTube IP-block / private / geo failure) happens LATER
// on the worker. The worker records the classified Russian message under the
// synthetic `ingest:<sha256(url)>` key; this route reads it OWNER-SCOPED so a
// failed link surfaces a LOUD user-facing error to the creator instead of a silent
// hang. A still-downloading link returns `pending`; a failed one returns the
// recorded message. Auth: Clerk userId (401 if absent); the read is filtered by
// that server-trusted userId, so a creator can only ever see their OWN failures.
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/** The synthetic ingest key shape: `ingest:` + a 64-char sha256 hex digest. */
const ingestIdSchema = z.string().regex(/^ingest:[0-9a-f]{64}$/);

interface RouteContext {
  params: Promise<{ ingestId: string }>;
}

export async function GET(_req: Request, context: RouteContext): Promise<Response> {
  const { userId } = await auth();
  if (!userId) {
    return Response.json({ error: 'unauthenticated' }, { status: 401 });
  }

  const { ingestId } = await context.params;
  const parsed = ingestIdSchema.safeParse(ingestId);
  if (!parsed.success) {
    return Response.json({ error: 'invalid ingestId' }, { status: 400 });
  }

  const failure = await findIngestFailure(db, userId, parsed.data);
  if (failure) {
    // A LOUD, classified failure: surface the worker's Russian user message verbatim.
    return Response.json(
      { status: 'failed', code: failure.code, error: failure.message },
      { status: 200, headers: { 'Cache-Control': 'no-store' } },
    );
  }

  // No failure recorded (yet): the download is still in flight, or it already
  // succeeded (its clips appear in the owner-wide "Мои клипы" history). Either way
  // there is nothing to surface as an error — keep polling.
  return Response.json(
    { status: 'pending' },
    { status: 200, headers: { 'Cache-Control': 'no-store' } },
  );
}
