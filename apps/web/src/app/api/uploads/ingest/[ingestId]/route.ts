// Async ingest-status poll — DISABLED (410 Gone).
//
// This route polled the outcome of a server-side URL download (see ../route.ts).
// That path is switched off (YouTube blocks our server IP), and the UI no longer
// submits links, so nothing reaches this poll. It is kept as an explicit 410 so a
// stale client polling an old ingestId gets a clear, classified response instead
// of a 404. Re-enabling the link feature means restoring the owner-scoped failure
// read here alongside ../route.ts and the dashboard UI.
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const DISABLED_ERROR = 'Загрузка по ссылке временно отключена. Загрузите видеофайл.';

export function GET(): Response {
  return Response.json(
    { error: DISABLED_ERROR },
    { status: 410, headers: { 'Cache-Control': 'no-store' } },
  );
}
