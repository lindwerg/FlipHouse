import { buildHealth, probeDb, probeRedis } from '@/libs/health';

// Node runtime so the pg/Drizzle probe works; always dynamic (never cached) so
// the healthcheck reflects live dependency state. Railway polls this path.
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(): Promise<Response> {
  const [dbStatus, redisStatus] = await Promise.all([probeDb(), probeRedis()]);
  const { payload, httpStatus } = buildHealth({ db: dbStatus, redis: redisStatus });

  return Response.json(payload, { status: httpStatus });
}
