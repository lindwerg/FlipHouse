import { sql } from 'drizzle-orm';
import { db } from '@/libs/DB';
import { redis } from '@/libs/Redis';

export type ProbeStatus = 'up' | 'down';

export type HealthPayload = {
  status: 'ok' | 'down';
  db: ProbeStatus;
  redis: ProbeStatus;
};

// Probes must never hang the healthcheck; Railway polls it on a tight schedule.
const PROBE_TIMEOUT_MS = 1000;

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return Promise.race([
    promise,
    new Promise<T>((_resolve, reject) => {
      setTimeout(() => reject(new Error('probe timeout')), ms);
    }),
  ]);
}

export async function probeDb(): Promise<ProbeStatus> {
  try {
    await withTimeout(db.execute(sql`select 1`), PROBE_TIMEOUT_MS);
    return 'up';
  } catch {
    return 'down';
  }
}

export async function probeRedis(): Promise<ProbeStatus> {
  try {
    await withTimeout(redis.ping(), PROBE_TIMEOUT_MS);
    return 'up';
  } catch {
    return 'down';
  }
}

// Pure aggregation — the db probe gates the HTTP status (Railway treats non-200
// as unhealthy); redis is reported but does not fail the check in P1.
export function buildHealth(probes: { db: ProbeStatus; redis: ProbeStatus }): {
  payload: HealthPayload;
  httpStatus: number;
} {
  const isDbUp = probes.db === 'up';
  return {
    payload: {
      status: isDbUp ? 'ok' : 'down',
      db: probes.db,
      redis: probes.redis,
    },
    httpStatus: isDbUp ? 200 : 503,
  };
}
