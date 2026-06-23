import { auth } from '@clerk/nextjs/server';
import { isIngestableUrl } from '@fliphouse/shared';
import * as z from 'zod';
import { enqueueIngest } from '@/features/ingest/enqueueIngest';

// Server-side URL ingestion (P2). A pasted YouTube/Vimeo/Dailymotion/Twitch link
// or a direct .mp4/.mov/.webm cannot be uploaded by the browser the way a File
// is — the bytes live on a third-party host. This route accepts the URL, stamps
// the server-trusted Clerk userId as the upload's owner (NEVER a client value,
// mirroring /api/uploads/grant), and enqueues ONE lightweight `ingest` job. The
// worker (yt-dlp + ffmpeg + R2 creds) downloads, content-hashes, writes the R2
// source object, and enqueues the SAME transcode→…→publish render flow a file
// upload does. We return 202 immediately — the download is async on the worker.
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const GENERIC_ERROR = 'Не удалось принять ссылку. Попробуйте ещё раз.';
const INVALID_URL_ERROR = 'Нужна ссылка на видео (YouTube, Vimeo, .mp4).';

const bodySchema = z.object({
  url: z.string().min(1),
});

export async function POST(req: Request): Promise<Response> {
  const { userId } = await auth();
  if (!userId) {
    return Response.json({ error: 'unauthenticated' }, { status: 401 });
  }

  const raw = await req.json().catch(() => null);
  const parsed = bodySchema.safeParse(raw);
  if (!parsed.success) {
    return Response.json({ error: INVALID_URL_ERROR }, { status: 400 });
  }

  const url = parsed.data.url.trim();
  if (!isIngestableUrl(url)) {
    return Response.json({ error: INVALID_URL_ERROR }, { status: 400 });
  }

  try {
    await enqueueIngest({ url, ownerId: userId });
  } catch {
    // A Redis/enqueue failure is genuine infra trouble — surface a generic 502 so
    // the dashboard shows a retryable error, never a leaked internal detail.
    return Response.json({ error: GENERIC_ERROR }, { status: 502 });
  }

  return Response.json({ status: 'queued' }, { status: 202 });
}
