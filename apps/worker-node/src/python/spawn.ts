import { spawn as nodeSpawn } from 'node:child_process';

import { stageResultSchema } from '@fliphouse/shared';
import type { StageRequest, StageResult } from '@fliphouse/shared';

import { resolvePythonEntry } from './resolve-entry.js';

/** stdout marker the Python CLI prefixes its single JSON envelope with. */
export const RESULT_FRAME_PREFIX = '@@FLIPHOUSE_RESULT@@';

/** Minimal child-process surface used by {@link runPythonStage} (injectable). */
export interface ChildLike {
  readonly stdout: { on(event: 'data', cb: (chunk: unknown) => void): void };
  readonly stderr: { on(event: 'data', cb: (chunk: unknown) => void): void };
  readonly stdin: { write(chunk: string): void; end(): void };
  readonly pid?: number | undefined;
  on(event: 'close', cb: (code: number | null, signal: NodeJS.Signals | null) => void): void;
  on(event: 'error', cb: (err: Error) => void): void;
  kill(signal?: NodeJS.Signals | number): boolean;
}

export type SpawnFn = (command: string, args: readonly string[]) => ChildLike;

export interface RunPythonStageOptions {
  readonly signal?: AbortSignal;
  readonly onStderrLine?: (line: string) => void;
  /** Test seams. */
  readonly _spawn?: SpawnFn;
  readonly _processKill?: (pid: number, signal: NodeJS.Signals) => void;
}

function retryable(code: string, message: string): StageResult {
  return { ok: false, kind: 'retryable', code, message };
}

/* v8 ignore start -- real process I/O; exercised in integration, not unit tests */
const defaultSpawn: SpawnFn = (command, args) =>
  nodeSpawn(command, [...args], { stdio: ['pipe', 'pipe', 'pipe'], detached: true }) as ChildLike;

const defaultProcessKill = (pid: number, signal: NodeJS.Signals): void => void process.kill(pid, signal);
/* v8 ignore stop */

/** Kill the whole process group (reaps ffmpeg grandchildren), falling back to the child. */
function killStage(child: ChildLike, processKill: (pid: number, signal: NodeJS.Signals) => void): void {
  const pid = child.pid;
  if (pid === undefined) {
    child.kill('SIGKILL');
    return;
  }
  try {
    processKill(-pid, 'SIGKILL');
  } catch {
    child.kill('SIGKILL');
  }
}

/** Extract and parse the last framed result envelope from accumulated stdout. */
function extractResult(stdout: string): StageResult | undefined {
  const lines = stdout.split('\n');
  for (const line of [...lines].reverse()) {
    if (!line.startsWith(RESULT_FRAME_PREFIX)) continue;
    try {
      const json: unknown = JSON.parse(line.slice(RESULT_FRAME_PREFIX.length));
      const parsed = stageResultSchema.safeParse(json);
      return parsed.success ? parsed.data : retryable('BAD_RESULT', 'result envelope failed schema');
    } catch {
      return retryable('BAD_RESULT', 'result envelope is not valid JSON');
    }
  }
  return undefined;
}

/**
 * Run one Python stage as an isolated subprocess and resolve its
 * {@link StageResult}. NEVER rejects: a crash/timeout/garbage output becomes a
 * `retryable` failure, and a framed envelope (incl. `ok:false`) is returned as
 * is so the caller classifies fatal vs retryable. Process isolation means a
 * segfault/OOM in ffmpeg/MediaPipe kills only the subprocess.
 */
export function runPythonStage(req: StageRequest, opts: RunPythonStageOptions = {}): Promise<StageResult> {
  /* v8 ignore next 2 -- the production default seams are covered by integration */
  const spawnFn = opts._spawn ?? defaultSpawn;
  const processKill = opts._processKill ?? defaultProcessKill;
  const entry = resolvePythonEntry();

  return new Promise<StageResult>((resolve) => {
    const child = spawnFn(entry.command, [...entry.baseArgs, req.stage]);
    const signal = opts.signal;
    let stdout = '';
    let stderrTail = '';
    let settled = false;

    function finish(result: StageResult): void {
      if (settled) return;
      settled = true;
      if (signal) signal.removeEventListener('abort', onAbort);
      resolve(result);
    }

    function onAbort(): void {
      killStage(child, processKill);
      finish(retryable('ABORTED', 'stage aborted by signal'));
    }

    if (signal?.aborted) {
      onAbort();
      return;
    }
    if (signal) signal.addEventListener('abort', onAbort);

    child.stdout.on('data', (chunk) => {
      stdout += String(chunk);
    });
    child.stderr.on('data', (chunk) => {
      stderrTail += String(chunk);
      const newlineIndex = stderrTail.lastIndexOf('\n');
      if (newlineIndex === -1) return;
      const complete = stderrTail.slice(0, newlineIndex);
      stderrTail = stderrTail.slice(newlineIndex + 1);
      if (opts.onStderrLine) for (const line of complete.split('\n')) opts.onStderrLine(line);
    });
    child.on('error', (err) => {
      finish(retryable('SPAWN_FAILED', err.message));
    });
    child.on('close', (code, closeSignal) => {
      const framed = extractResult(stdout);
      if (framed) {
        finish(framed);
        return;
      }
      if (closeSignal) {
        finish(retryable('KILLED', `subprocess killed by ${closeSignal}`));
        return;
      }
      finish(retryable('NO_RESULT', `no framed result on stdout (exit ${String(code)})`));
    });

    child.stdin.write(JSON.stringify(req));
    child.stdin.end();
  });
}
