import { createServer as createHttpServer } from 'node:http';
import type { IncomingMessage, Server, ServerResponse } from 'node:http';
import { pathToFileURL } from 'node:url';

import { handleCallback } from './handle-callback.js';
import type { CallbackDeps } from './handle-callback.js';
import { buildRealDeps } from './real-deps.js';

/* v8 ignore start -- HTTP bootstrap + process.env + signals; integration-only, exercised on deploy */

/**
 * GigaAM-v3 ASR callback HTTP bootstrap (P2 step #1, TRACK B). The GPU
 * transcription worker POSTs prediction outcomes here once a long-running ASR
 * job finishes. Wiring lives in {@link buildRealDeps}: the SINGLE atomic dedup
 * (`GETDEL park:<request_id>`), the R2 raw-payload write, and the `asr-resume`
 * BullMQ enqueue/fail. This file owns only HTTP framing, header extraction, and
 * the verify→parse→claim→act dispatch into {@link handleCallback}.
 */

/** The single path the GPU caller POSTs ASR outcomes to. */
const CALLBACK_PATH = '/gpu/callback';

/** Signature header carrying `sha256=<hex>` of HMAC over `${timestamp}.${rawBody}`. */
const SIGNATURE_HEADER = 'x-fliphouse-signature';

/** Unix-seconds timestamp header, bound into the signed message and replay-windowed. */
const TIMESTAMP_HEADER = 'x-fliphouse-timestamp';

const DEFAULT_HOST = '::';
const DEFAULT_PORT = 8080;
const MAX_BODY_BYTES = 1_048_576;

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { 'content-type': 'application/json' });
  res.end(JSON.stringify(body));
}

function readRawBody(stream: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let total = 0;
    stream.on('data', (chunk: Buffer) => {
      total += chunk.length;
      if (total > MAX_BODY_BYTES) {
        reject(new Error('request body too large'));
        return;
      }
      chunks.push(chunk);
    });
    stream.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    stream.on('error', reject);
  });
}

function headerString(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value[0] ?? '';
  return value ?? '';
}

async function handleRequest(
  req: IncomingMessage,
  res: ServerResponse,
  deps: CallbackDeps,
): Promise<void> {
  if (req.method !== 'POST' || req.url !== CALLBACK_PATH) {
    sendJson(res, 404, { error: 'not found' });
    return;
  }
  let rawBody: string;
  try {
    rawBody = await readRawBody(req);
  } catch {
    // Oversize / unreadable body, BEFORE any HMAC work → client fault.
    sendJson(res, 400, { error: 'invalid request body' });
    return;
  }
  const signature = headerString(req.headers[SIGNATURE_HEADER]);
  const timestamp = headerString(req.headers[TIMESTAMP_HEADER]);
  try {
    const outcome = await handleCallback(rawBody, signature, timestamp, deps);
    sendJson(res, outcome.kind === 'hmac-invalid' ? 401 : 200, { kind: outcome.kind });
  } catch (error) {
    // HMAC is verified FIRST, so a throw here is a verified-but-malformed body —
    // a real contract breach. Log the detail server-side; return a GENERIC 422
    // (never echo error.message: info-leak; never 200: that would swallow it).
    process.stderr.write(`gpu-callback: verified-but-malformed body: ${String(error)}\n`);
    sendJson(res, 422, { error: 'unprocessable callback' });
  }
}

/** A node:http server routing POST /gpu/callback to the verified callback handler. */
export function createServer(deps: CallbackDeps): Server {
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

export interface RunningServer {
  readonly shutdown: () => Promise<void>;
}

/**
 * Boot the webhook receiver. `GIGAAM_WEBHOOK_SECRET` and `REDIS_URL` plus the R2
 * vars are mandatory; absence aborts the start (fail-fast on Railway).
 */
export async function runServer(
  env: Record<string, string | undefined> = process.env,
): Promise<RunningServer> {
  const secret = requireEnv(env, 'GIGAAM_WEBHOOK_SECRET');
  const redisUrl = requireEnv(env, 'REDIS_URL');
  const { deps, close } = buildRealDeps({ secret, redisUrl, r2Env: env });
  const server = createServer(deps);

  const host = env.HOST ?? DEFAULT_HOST;
  const port = Number(env.PORT) || DEFAULT_PORT;

  await new Promise<void>((resolve) => server.listen(port, host, resolve));

  const shutdown = (): Promise<void> =>
    new Promise<void>((resolve) => {
      server.close(() => {
        close().then(
          () => resolve(),
          () => resolve(),
        );
      });
    });
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
    process.stderr.write(`webhook-receiver bootstrap failed: ${String(err)}\n`);
    process.exit(1);
  });
}

/* v8 ignore stop */
