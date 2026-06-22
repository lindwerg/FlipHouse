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
// resolved through the R2 public-base seam. Never cached.
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

  return Response.json(
    { status: owned.status, clips: owned.clips.map(toClipView) },
    { status: 200, headers: { 'Cache-Control': 'no-store' } },
  );
}
