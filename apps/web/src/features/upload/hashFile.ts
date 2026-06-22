import { isValidContentHash } from './content-hash';
import { hashStream } from './streaming-hash';

// Content-hash a selected video File into the 64-char lowercase hex sha256 the
// tusd post-finish hook claims the ledger by. The heavy work (reading a multi-GB
// file as a stream) runs OFF the main thread in a Web Worker by default, so the
// dashboard stays responsive while a large upload is fingerprinted. The Worker
// glue is the only non-unit-testable seam; the pure hashing it performs lives in
// streaming-hash.ts and is exercised directly here via `runInProcess`.

/** Thrown when a runner yields something that is not a valid content hash. */
export const HASH_INVALID_ERROR = 'hashFile: runner returned an invalid sha256 digest';

/** Runs the streaming hash for a File and resolves its hex digest. */
export type HashRunner = (file: File) => Promise<string>;

export interface HashFileOptions {
  /** Inject a runner (tests, or a server-side path). Overrides the default Worker. */
  runner?: HashRunner;
  /** Run the hash on the current thread instead of a Worker (tests, SSR). */
  runInProcess?: boolean;
}

/** Hash a File on the current thread by streaming its bytes — no Worker. */
async function inProcessRunner(file: File): Promise<string> {
  return hashStream(file.stream());
}

/* v8 ignore start -- Web Worker glue: `new Worker(new URL(...))` + postMessage
   round-trip cannot run under jsdom/node and is covered by E2E, not unit tests.
   The hashing logic it delegates to (streaming-hash.ts) is unit-tested directly. */
function workerRunner(file: File): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    const worker = new Worker(new URL('./hash.worker.ts', import.meta.url), {
      type: 'module',
    });
    worker.addEventListener('message', (event: MessageEvent<{ digest?: string; error?: string }>) => {
      const { digest, error } = event.data;
      worker.terminate();
      if (typeof digest === 'string') {
        resolve(digest);
      } else {
        reject(new Error(error ?? 'hash worker failed'));
      }
    });
    worker.addEventListener('error', (event) => {
      worker.terminate();
      reject(new Error(event.message));
    });
    worker.postMessage(file);
  });
}
/* v8 ignore stop */

function pickRunner(options: HashFileOptions): HashRunner {
  if (options.runner) {
    return options.runner;
  }
  if (options.runInProcess) {
    return inProcessRunner;
  }
  /* v8 ignore next -- default browser path: selects the Worker runner, which can
     only execute in a real Worker context (see workerRunner). */
  return workerRunner;
}

/**
 * Content-hash a File to a 64-char lowercase hex sha256. Validates the runner's
 * output at the boundary so a corrupt/short digest can never be sent as upload
 * metadata (the hook rejects a non-hex sha256 as `hash-required`).
 */
export async function hashFile(file: File, options: HashFileOptions = {}): Promise<string> {
  const runner = pickRunner(options);
  const digest = await runner(file);
  if (!isValidContentHash(digest)) {
    throw new Error(HASH_INVALID_ERROR);
  }
  return digest;
}
