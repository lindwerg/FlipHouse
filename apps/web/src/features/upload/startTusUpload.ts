import { Upload } from 'tus-js-client';

// Resumable upload via tus (P2.2). The browser PATCHes video bytes to tusd; on
// finish tusd POSTs apps/hook-receiver's post-finish hook, which reads exactly
// the `ownerId` + `sha256` metadata we stamp here to claim the ledger and enqueue
// the flow. This module isolates the tus.Upload construction behind an injectable
// factory so the metadata contract + resume-before-start sequencing are unit-
// testable without a real PATCH or browser.

/**
 * Retry backoff (ms) for transient PATCH failures — mid-upload network blips.
 * Mutable because tus-js-client's `retryDelays` option is a mutable `number[]`;
 * we copy it per-upload (in the options below) so callers never mutate it.
 */
export const TUS_RETRY_DELAYS: ReadonlyArray<number> = [0, 3000, 5000, 10000, 20000];

/** A previously-stored upload tus can resume from (opaque to us). */
export type TusPreviousUpload = { readonly urlStorageKey: string };

/** The slice of tus.Upload's option surface this module sets. */
export interface TusUploadOptions {
  endpoint: string;
  metadata: Record<string, string>;
  retryDelays: number[];
  removeFingerprintOnSuccess: boolean;
  onProgress?: (bytesSent: number, bytesTotal: number) => void;
  onSuccess?: (payload: unknown) => void;
  onError?: (error: Error) => void;
}

/** The slice of tus.Upload's instance surface this module drives. */
export interface TusUpload {
  findPreviousUploads(): Promise<ReadonlyArray<TusPreviousUpload>>;
  resumeFromPreviousUpload(previous: TusPreviousUpload): void;
  start(): void;
  abort(shouldTerminate?: boolean): Promise<void>;
}

/** Builds a tus.Upload for `file` with `options`. Injectable for tests. */
export type TusUploadFactory = (file: File, options: TusUploadOptions) => TusUpload;

export interface StartTusUploadArgs {
  endpoint: string;
  /** Server-trusted Clerk userId (from /api/uploads/grant) — the hook claims by it. */
  ownerId: string;
  /** Client-streamed content hash; MUST be a 64-char lowercase hex sha256. */
  sha256: string;
  onProgress?: (bytesSent: number, bytesTotal: number) => void;
  onSuccess?: () => void;
  onError?: (error: Error) => void;
  uploadFactory?: TusUploadFactory;
}

/** A running upload the caller can cancel. */
export interface TusUploadHandle {
  abort(): Promise<void>;
}

/* v8 ignore start -- default factory constructs the real tus.Upload (network +
   browser PATCH); covered by E2E. The orchestration around it is unit-tested via
   an injected factory. */
const defaultUploadFactory: TusUploadFactory = (file, options) =>
  new Upload(file, options) as unknown as TusUpload;

function resolveFactory(injected: TusUploadFactory | undefined): TusUploadFactory {
  return injected ?? defaultUploadFactory;
}
/* v8 ignore stop */

/**
 * Stamp the upload's metadata, check for a resumable previous attempt (free
 * resume-across-reload), and start the upload. Resolves once the upload has been
 * started — progress/success/error arrive via the callbacks.
 */
export async function startTusUpload(
  file: File,
  args: StartTusUploadArgs,
): Promise<TusUploadHandle> {
  const factory = resolveFactory(args.uploadFactory);

  const options: TusUploadOptions = {
    endpoint: args.endpoint,
    metadata: {
      ownerId: args.ownerId,
      sha256: args.sha256,
      filename: file.name,
      filetype: file.type,
    },
    retryDelays: [...TUS_RETRY_DELAYS],
    removeFingerprintOnSuccess: true,
    onProgress: args.onProgress,
    onSuccess: args.onSuccess ? () => args.onSuccess?.() : undefined,
    onError: args.onError,
  };

  const upload = factory(file, options);

  const previous = await upload.findPreviousUploads();
  const first = previous.at(0);
  if (first) {
    upload.resumeFromPreviousUpload(first);
  }
  upload.start();

  return {
    abort: () => upload.abort(true),
  };
}
