import { createHash } from 'node:crypto';
import { auth } from '@clerk/nextjs/server';
import { claimUpload, finishUpload, upsertClips } from '@fliphouse/db';
import type { ClipInput } from '@fliphouse/db';
import * as z from 'zod';
import { db } from '@/libs/DB';

// DEV/E2E-ONLY: deterministically seeds a finished upload + its ranked clips for
// the signed-in creator so the upload-to-clips e2e can assert the dashboard
// surface (RankedBatchView / "Мои клипы") WITHOUT a live tusd + GPU pipeline.
// Re-seeding the SAME `seed` is a no-op via the upload ledger's content-hash
// claim (the durable idempotency authority) — `claimed: false` on the second
// call proves the upload-reuse path. Hard 403 in production so it never ships.
//
// Presigning still goes through the real /api/uploads read path, so a seeded
// clipUrl is a stored R2 object KEY — the dashboard renders a <video> whose
// <source src> is a short-lived presigned GET. Playback to readyState>=2 needs a
// live R2 object; the spec documents that and falls back to asserting the
// element + presigned src when R2 is not reachable.
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const DEFAULT_CLIP_COUNT = 3;
const MAX_CLIP_COUNT = 10;

const bodySchema = z.object({
  // Stable label → a deterministic 64-hex content hash, so a test owns a fresh
  // upload per `seed` and re-seeding the same label is idempotent.
  seed: z.string().min(1).default('e2e'),
  clipCount: z.number().int().min(1).max(MAX_CLIP_COUNT).default(DEFAULT_CLIP_COUNT),
});

/** Deterministic 64-char lowercase hex content hash from a (user, seed) pair. */
function deriveContentHash(ownerId: string, seed: string): string {
  return createHash('sha256').update(`${ownerId}:${seed}`).digest('hex');
}

// Descending scores so rank 0 is the best clip — the dashboard orders by rank
// asc, which must coincide with score desc for a correctly-ranked batch.
const SUB_SCORES = { hook: 80, retention: 75, payoff: 70 } as const;
const MODALITIES = ['video', 'audio', 'transcript'] as const;

function makeClips(contentHash: string, count: number): readonly ClipInput[] {
  return Array.from({ length: count }, (_unused, rank) => {
    const start = rank * 60;
    const end = start + 45;
    return {
      rank,
      // numeric columns are inserted as strings (drizzle numeric mode).
      score: (95 - rank * 7).toFixed(4),
      subScores: SUB_SCORES,
      confidence: 90,
      startTime: start.toFixed(3),
      endTime: end.toFixed(3),
      durationS: (end - start).toFixed(3),
      width: 1080,
      height: 1920,
      clipUrl: `clips/${contentHash}/rank-${rank}.mp4`,
      title: `Клип №${rank + 1}`,
      usedVideo: true,
      modelUsed: 'gemini-3.5-flash',
      modalitiesUsed: MODALITIES,
      manifestSchemaVersion: 1,
      engine: 'e2e-seed',
    } satisfies ClipInput;
  });
}

export async function POST(req: Request): Promise<Response> {
  if (process.env.NODE_ENV === 'production') {
    return Response.json({ error: 'not found' }, { status: 403 });
  }

  const { userId } = await auth();
  if (!userId) {
    return Response.json({ error: 'unauthenticated' }, { status: 401 });
  }

  const raw = await req.json().catch(() => ({}));
  const { seed, clipCount } = bodySchema.parse(raw ?? {});

  const contentHash = deriveContentHash(userId, seed);

  // claimUpload is the durable idempotency authority: the first seed inserts and
  // wins; a re-seed of the same hash returns claimed:false (the upload-reuse path).
  const claim = await claimUpload(db, {
    contentHash,
    ownerId: userId,
    firstUploadId: `e2e-${seed}`,
    tusObjectKey: `uploads/${contentHash}.mp4`,
  });

  // Always (re)write the deterministic clips + mark done so the dashboard read is
  // stable across re-seeds (upsertClips replaces atomically).
  await upsertClips(db, contentHash, makeClips(contentHash, clipCount));
  await finishUpload(db, contentHash, {
    resultUrl: `clips/${contentHash}/manifest.json`,
    manifestUrl: `clips/${contentHash}/manifest.json`,
    engine: 'e2e-seed',
    durationSec: clipCount * 60,
  });

  return Response.json(
    { contentHash, claimed: claim.claimed, clipCount },
    { status: 200, headers: { 'Cache-Control': 'no-store' } },
  );
}
