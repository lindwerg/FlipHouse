import { createServer as createHttpServer } from 'node:http';
import type { IncomingMessage, Server, ServerResponse } from 'node:http';
import { pathToFileURL } from 'node:url';

import { handleCallback } from './handle-callback.js';
import type { CallbackDeps } from './handle-callback.js';
import { verifyHmac } from './verify-hmac.js';

/* v8 ignore start -- HTTP bootstrap + process.env + signals; dormant in P2, exercised on deploy */

/**
 * GPU-callback HTTP bootstrap (spec §6.12). DORMANT in P2: no GPU provider calls
 * this in the CPU path, so it is not deployed and carries no live traffic. The
 * contract is nonetheless complete and tested via {@link handleCallback}. The
 * seam to activate the GPU path is `buildCallbackDeps`: wire the real atomic
 * `claimPrediction` (Redis GETDEL) and `resumeParkedJob` from
 * `@fliphouse/worker-node` state/park.ts here.
 */

/** The single path our GPU caller POSTs prediction outcomes to. */
const CALLBACK_PATH = '/gpu/callback';

/** Our own signature header carrying `sha256=<hex>` of the raw body (HMAC-SHA256). */
const SIGNATURE_HEADER = 'x-fliphouse-signature';

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

/**
 * P2 dormant deps. TODO(GPU): when the GPU path activates, wire a SINGLE source
 * of atomicity for dedup — the GETDEL on `park:<predictionId>` must happen in ONE
 * place, not twice. state/park.ts `resumeParkedJob` already does its own GETDEL,
 * so either `claimPrediction` performs the GETDEL and `resumeParkedJob` trusts
 * it, or vice-versa — never both (a double-GETDEL would make the second a no-op
 * and could drop the resume). Add an integration test proving a duplicate
 * delivery is an end-to-end no-op, and keep this server unexposed until then.
 * Until activation `claimPrediction` always claims and `resumeParkedJob` is a
 * deliberate noop (no live dedup table yet).
 */
function buildCallbackDeps(secret: string): CallbackDeps {
  return {
    verifyHmacFn: (rawBody, signatureHeader) => verifyHmac(secret, rawBody, signatureHeader),
    claimPrediction: async () => true,
    resumeParkedJob: async () => {},
  };
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
  try {
    const outcome = await handleCallback(rawBody, signature, deps);
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

/** Boot the webhook receiver. WEBHOOK_SECRET is mandatory; absence aborts the start. */
export async function runServer(
  env: Record<string, string | undefined> = process.env,
): Promise<RunningServer> {
  const secret = requireEnv(env, 'WEBHOOK_SECRET');
  const server = createServer(buildCallbackDeps(secret));

  const host = env.HOST ?? DEFAULT_HOST;
  const port = Number(env.PORT) || DEFAULT_PORT;

  await new Promise<void>((resolve) => server.listen(port, host, resolve));

  const shutdown = (): Promise<void> =>
    new Promise<void>((resolve) => server.close(() => resolve()));
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
