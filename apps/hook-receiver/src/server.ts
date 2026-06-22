import { createServer as createHttpServer } from 'node:http';
import type { IncomingMessage, Server, ServerResponse } from 'node:http';
import { pathToFileURL } from 'node:url';

import { createFlowProducer } from '@fliphouse/worker-node/flow';
import { redisConnectionFromUrl } from '@fliphouse/worker-node/queues';
import { Pool } from 'pg';

import { handlePostFinish } from './handle-post-finish.js';
import type { PostFinishDeps } from './handle-post-finish.js';
import { mapOutcomeToStatus, parseRequestBody } from './http-router.js';
import { buildRealDeps, buildSweepDeps } from './real-deps.js';
import { sweepStuckFlows } from './reconcile-sweep.js';

/* v8 ignore start -- HTTP/Redis/pg bootstrap + process signals; exercised on deploy, not unit tests */

/** The single hook path tusd POSTs after a completed upload. */
const POST_FINISH_PATH = '/tus/post-finish';

/** Defaults chosen for Railway: IPv6 all-interfaces, 5-min grace, 1-min sweep cadence. */
const DEFAULT_HOST = '::';
const DEFAULT_PORT = 8080;
const DEFAULT_SWEEP_GRACE_MS = 5 * 60_000;
const DEFAULT_SWEEP_INTERVAL_MS = 60_000;

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body);
  res.writeHead(status, { 'content-type': 'application/json' });
  res.end(payload);
}

async function handleRequest(
  req: IncomingMessage,
  res: ServerResponse,
  deps: PostFinishDeps,
): Promise<void> {
  if (req.method !== 'POST' || req.url !== POST_FINISH_PATH) {
    sendJson(res, 404, { error: 'not found' });
    return;
  }
  let body: unknown;
  try {
    body = await parseRequestBody(req);
  } catch {
    // Malformed JSON / oversize body is a CLIENT fault → 400, not a retryable 5xx.
    sendJson(res, 400, { error: 'invalid request body' });
    return;
  }
  try {
    const outcome = await handlePostFinish(body, deps);
    sendJson(res, mapOutcomeToStatus(outcome), { kind: outcome.kind });
  } catch (error) {
    // Reserved for genuine infra failure (pg/Redis) — the only case tusd should retry.
    sendJson(res, 500, { error: error instanceof Error ? error.message : 'internal error' });
  }
}

/** A node:http server that routes POST /tus/post-finish to the post-finish handler. */
export function createServer(deps: PostFinishDeps): Server {
  return createHttpServer((req, res) => {
    handleRequest(req, res, deps).catch((error: unknown) => {
      sendJson(res, 500, { error: error instanceof Error ? error.message : 'internal error' });
    });
  });
}

function requireEnv(env: Record<string, string | undefined>, name: string): string {
  const value = env[name];
  if (!value) {
    throw new Error(`missing required env var: ${name}`);
  }
  return value;
}

function numberEnv(value: string | undefined, fallback: number): number {
  if (value === undefined) {
    return fallback;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export interface RunningServer {
  readonly shutdown: () => Promise<void>;
}

/**
 * Boot the hook receiver: a pg Pool + FlowProducer feed both the HTTP handler and
 * the reconcile-sweep timer. The sweep re-enqueues flows orphaned by a crash
 * between claim and enqueue. SIGTERM drains the timer, server, pool and producer.
 */
export async function runServer(
  env: Record<string, string | undefined> = process.env,
): Promise<RunningServer> {
  const pool = new Pool({ connectionString: requireEnv(env, 'DATABASE_URL') });
  const connection = redisConnectionFromUrl(requireEnv(env, 'REDIS_URL'));
  const producer = createFlowProducer(connection);

  const server = createServer(buildRealDeps(pool, producer));
  const sweepDeps = buildSweepDeps(pool, producer);

  const host = env.HOST ?? DEFAULT_HOST;
  const port = numberEnv(env.PORT, DEFAULT_PORT);
  const graceMs = numberEnv(env.SWEEP_GRACE_TTL_MS, DEFAULT_SWEEP_GRACE_MS);
  const intervalMs = numberEnv(env.SWEEP_INTERVAL_MS, DEFAULT_SWEEP_INTERVAL_MS);

  await new Promise<void>((resolve) => server.listen(port, host, resolve));

  const sweepTimer = setInterval(() => {
    sweepStuckFlows(sweepDeps, graceMs).catch((error: unknown) => {
      process.stderr.write(`reconcile-sweep failed: ${String(error)}\n`);
    });
  }, intervalMs);
  sweepTimer.unref();

  const shutdown = async (): Promise<void> => {
    clearInterval(sweepTimer);
    await new Promise<void>((resolve) => server.close(() => resolve()));
    await producer.close();
    await pool.end();
  };
  return { shutdown };
}

function installSignalHandlers(running: RunningServer): void {
  for (const signal of ['SIGTERM', 'SIGINT'] as const) {
    process.once(signal, () => {
      running.shutdown().then(
        () => process.exit(0),
        () => process.exit(1),
      );
    });
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  runServer().then(installSignalHandlers, (err: unknown) => {
    process.stderr.write(`hook-receiver bootstrap failed: ${String(err)}\n`);
    process.exit(1);
  });
}

/* v8 ignore stop */
