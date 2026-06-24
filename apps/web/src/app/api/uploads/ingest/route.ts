// Server-side URL ingestion — DISABLED (410 Gone).
//
// The pasted-link path (POST a YouTube/Vimeo/etc. URL → server-side yt-dlp
// download into the render pipeline) was switched off: YouTube blocks our server
// IP, so server-side downloads are unreliable. The dashboard UI no longer offers
// a "paste a link" affordance; only direct FILE upload (tus) remains. The route
// is kept as an explicit 410 so any stale client, bookmark, or replayed request
// gets a clear, classified response instead of a confusing 404 or a silent enqueue.
//
// The worker-side ingest consumer (apps/worker-node) and the shared ingest helpers
// stay intact so the link feature can be re-enabled later by restoring this route
// and the UI — nothing here is deleted from the cross-package seam.
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const DISABLED_ERROR = 'Загрузка по ссылке временно отключена. Загрузите видеофайл.';

export function POST(): Response {
  return Response.json(
    { error: DISABLED_ERROR },
    { status: 410, headers: { 'Cache-Control': 'no-store' } },
  );
}
