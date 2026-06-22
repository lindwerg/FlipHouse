import { createSHA256 } from 'hash-wasm';

// Pure, environment-agnostic streaming SHA-256. Drives a ReadableStream<Uint8Array>
// through hash-wasm chunk-by-chunk so a multi-GB upload never materialises a full
// ArrayBuffer in memory. The digest is byte-identical to packages/shared
// `sha256Hex` over the same bytes — that equality is the load-bearing contract:
// the tusd post-finish hook claims the ledger by this exact hash, and a future
// server re-verify must line up. Lives apart from the File/Worker glue so it is
// unit-testable with a fabricated stream.

/** A minimal incremental hasher — matches hash-wasm's `IHasher` surface we use. */
export interface IncrementalHasher {
  init(): IncrementalHasher;
  update(data: Uint8Array): IncrementalHasher;
  digest(encoding: 'hex'): string;
}

export type HasherFactory = () => Promise<IncrementalHasher>;

/**
 * SHA-256 of every byte read from `stream`, as a 64-char lowercase hex string.
 * `createHasher` is injectable so tests can swap the implementation; it defaults
 * to hash-wasm's SHA-256.
 */
export async function hashStream(
  stream: ReadableStream<Uint8Array>,
  createHasher: HasherFactory = createSHA256,
): Promise<string> {
  const hasher = await createHasher();
  hasher.init();

  const reader = stream.getReader();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      if (value !== undefined) {
        hasher.update(value);
      }
    }
  } finally {
    reader.releaseLock();
  }

  return hasher.digest('hex');
}
