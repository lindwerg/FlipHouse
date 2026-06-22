import { auth } from '@clerk/nextjs/server';
import { Env } from '@/libs/Env';

// Upload grant (P2.2). The dashboard uploader fetches this BEFORE starting a tus
// upload to learn (1) whom to stamp as the upload's `ownerId` metadata — the
// server-trusted Clerk userId, never a client-supplied value — and (2) the tusd
// endpoint to PATCH bytes to. The tusd post-finish hook (apps/hook-receiver)
// reads exactly `MetaData.ownerId` to claim the ledger, so this id is the single
// source of truth for upload ownership.
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(_req: Request): Promise<Response> {
  const { userId } = await auth();
  if (!userId) {
    return Response.json({ error: 'unauthenticated' }, { status: 401 });
  }

  return Response.json(
    { ownerId: userId, tusEndpoint: Env.NEXT_PUBLIC_TUS_ENDPOINT },
    { status: 200 },
  );
}
