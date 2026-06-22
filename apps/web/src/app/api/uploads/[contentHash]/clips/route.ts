import { auth } from '@clerk/nextjs/server';
import { listClipsForOwner } from '@fliphouse/db';
import { contentHashParamSchema } from '@/features/results/api-schemas';
import { toClipView } from '@/features/results/clip-mapper';
import { db } from '@/libs/DB';

// Owner-scoped ranked-clips read for the creator dashboard (P2.3). Auth flow:
// Clerk userId (401 if absent) → validate the contentHash path param (400 if
// malformed) → listClipsForOwner returns null for a missing OR wrong-owner row
// (→ 404, so a forged hash never confirms another creator's upload exists). On
// success: 200 { status, clips } with numeric columns coerced and each clipUrl
// resolved to a short-lived presigned GET URL (the clip bucket is private-read).
// Presigning needs node crypto + server credentials → Node runtime. Never cached.
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

interface RouteContext {
  params: Promise<{ contentHash: string }>;
}

export async function GET(_req: Request, context: RouteContext): Promise<Response> {
  const { userId } = await auth();
  if (!userId) {
    return Response.json({ error: 'unauthenticated' }, { status: 401 });
  }

  const { contentHash } = await context.params;
  const parsed = contentHashParamSchema.safeParse(contentHash);
  if (!parsed.success) {
    return Response.json({ error: 'invalid contentHash' }, { status: 400 });
  }

  const owned = await listClipsForOwner(db, parsed.data, userId);
  if (!owned) {
    return Response.json({ error: 'not found' }, { status: 404 });
  }

  const clips = await Promise.all(owned.clips.map(toClipView));
  return Response.json(
    { status: owned.status, clips },
    { status: 200, headers: { 'Cache-Control': 'no-store' } },
  );
}
