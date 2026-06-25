import { pino, type Logger } from 'pino';

/**
 * The one structured logger for the Node worker (OBS-3).
 *
 * Before this, the only output channels were two raw `process.stderr.write`
 * calls (run-workers/projector) — a flapping Redis, a `failed` BullMQ job, or a
 * swallowed projector write produced NOTHING actionable in the Railway logs. A
 * single pino instance gives every site structured `{level,fields,msg}` JSON the
 * log pipeline can parse and alert on.
 *
 * Level comes from `LOG_LEVEL` (default `info`). In production we emit raw JSON
 * (Railway ingests it as-is); in dev `pino-pretty` is opt-in via `LOG_PRETTY`
 * but never required, so the worker has no hard dev-tooling dependency.
 */
export function createLogger(env: Record<string, string | undefined> = process.env): Logger {
  const level = env.LOG_LEVEL ?? 'info';
  const base = { service: 'worker-node' };
  /* v8 ignore start -- pretty transport is an opt-in dev convenience, not unit-tested */
  if (env.LOG_PRETTY === 'true') {
    return pino({ level, base, transport: { target: 'pino-pretty' } });
  }
  /* v8 ignore stop */
  return pino({ level, base });
}

/** Process-wide logger; child loggers (`log.child({stage})`) tag per-context fields. */
export const log: Logger = createLogger();
