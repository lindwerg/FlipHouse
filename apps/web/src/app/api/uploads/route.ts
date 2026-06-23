import { auth } from '@clerk/nextjs/server';
import type { ClipDashboardRow } from '@fliphouse/db';
import { listUploadsForOwner } from '@fliphouse/db';
import type { ClipView, OwnerUploadView } from '@/features/results/api-schemas';
import { toClipView } from '@/features/results/clip-mapper';
import { db } from '@/libs/DB';

// Owner-wide upload history for the creator dashboard's "Мои клипы" section.
// Unlike [contentHash]/clips (one upload by hash), this lists EVERY upload the
// authenticated creator owns — across all statuses, newest-first — so finished
// clips survive a page refresh even when no in-session contentHash exists. Auth
// flow: Clerk userId (401 if absent) → listUploadsForOwner is STRICTLY scoped to
// that userId (the owner is NEVER taken from the client, mirroring the clips
// route's security posture, so a creator only ever sees their own rows). Each
// stored clip key is resolved to a short-lived presigned GET URL (private clip
// bucket). Presigning needs node crypto + server credentials → Node runtime.
// Never cached.
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// Cap on concurrent R2 presign requests in flight. The owner history fans out
// across EVERY clip of EVERY upload (up to ~50 uploads), so — unlike the
// single-upload /clips route — the presigns are bounded by a worker pool to keep
// one creator's page load from saturating the S3 connection pool.
const PRESIGN_CONCURRENCY = 8;

/**
 * Presign a flat list of clip rows with at most {@link PRESIGN_CONCURRENCY}
 * requests in flight, preserving input order. A small fixed-size pool of workers
 * pulls from a shared cursor — no external dependency.
 */
async function presignAll(rows: readonly ClipDashboardRow[]): Promise<ClipView[]> {
  const views = new Array<ClipView>(rows.length);
  let next = 0;
  const worker = async (): Promise<void> => {
    for (let i = next++; i < rows.length; i = next++) {
      views[i] = await toClipView(rows[i]!);
    }
  };
  const pool = Math.min(PRESIGN_CONCURRENCY, rows.length);
  await Promise.all(Array.from({ length: pool }, worker));
  return views;
}

export async function GET(): Promise<Response> {
  const { userId } = await auth();
  if (!userId) {
    return Response.json({ error: 'unauthenticated' }, { status: 401 });
  }

  const uploads = await listUploadsForOwner(db, userId);

  // Flatten every clip across every upload, presign with a bounded pool, then
  // slice the results back onto each upload in order (the clip bucket is
  // private-read so each stored key becomes a short-lived presigned GET URL).
  const flatClips = uploads.flatMap((upload) => upload.clips);
  const flatViews = await presignAll(flatClips);

  let offset = 0;
  const views: OwnerUploadView[] = uploads.map((upload) => {
    const clips = flatViews.slice(offset, offset + upload.clips.length);
    offset += upload.clips.length;
    return {
      contentHash: upload.contentHash,
      status: upload.status,
      durationSec: upload.durationSec,
      createdAt: upload.createdAt.toISOString(),
      clips,
    };
  });

  return Response.json(
    { uploads: views },
    { status: 200, headers: { 'Cache-Control': 'no-store' } },
  );
}
