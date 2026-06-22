'use client';

import { useCallback, useRef, useState } from 'react';
import * as z from 'zod';
import { hashFile as defaultHashFile } from './hashFile';
import type { StartTusUploadArgs, TusUploadHandle } from './startTusUpload';
import { startTusUpload as defaultStartTusUpload } from './startTusUpload';

// Orchestrates the creator upload path (P2.2): grant → content-hash → resumable
// tus upload. Owns a small status machine (idle → hashing → uploading → done,
// or → error) the dashboard panel renders. Every side-effecting boundary (the
// grant fetch, the Worker hash, the tus PATCH) is an injectable dep so the
// machine is unit-tested with no network, Worker, or real upload.

export type UploadStatus = 'idle' | 'hashing' | 'uploading' | 'done' | 'error';

const GENERIC_ERROR = 'Не удалось загрузить видео';

/** Shape returned by GET /api/uploads/grant — validated at the fetch boundary. */
export const grantSchema = z.object({
  ownerId: z.string().min(1),
  tusEndpoint: z.string().url(),
});

export type UploadGrant = z.infer<typeof grantSchema>;

export type FetchGrant = () => Promise<UploadGrant>;
export type HashFile = (file: File) => Promise<string>;
export type StartTusUpload = (file: File, args: StartTusUploadArgs) => Promise<TusUploadHandle>;

export interface UseVideoUploadDeps {
  fetchGrant: FetchGrant;
  hashFile: HashFile;
  startTusUpload: StartTusUpload;
}

export interface UseVideoUpload {
  status: UploadStatus;
  progress: number;
  error: string | null;
  flip: (file: File) => Promise<void>;
}

/* v8 ignore start -- default browser deps: a real fetch + Worker hash + tus PATCH.
   Covered by E2E; the hook logic is unit-tested with injected deps. */
const defaultFetchGrant: FetchGrant = async () => {
  const res = await fetch('/api/uploads/grant');
  if (!res.ok) {
    throw new Error('unauthenticated');
  }
  return grantSchema.parse(await res.json());
};

const DEFAULT_DEPS: UseVideoUploadDeps = {
  fetchGrant: defaultFetchGrant,
  hashFile: file => defaultHashFile(file),
  startTusUpload: defaultStartTusUpload,
};
/* v8 ignore stop */

function toMessage(error: unknown): string {
  return error instanceof Error ? error.message : GENERIC_ERROR;
}

export function useVideoUpload(deps: UseVideoUploadDeps = DEFAULT_DEPS): UseVideoUpload {
  const [status, setStatus] = useState<UploadStatus>('idle');
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const handleRef = useRef<TusUploadHandle | null>(null);

  const flip = useCallback(
    async (file: File): Promise<void> => {
      setError(null);
      setProgress(0);
      setStatus('hashing');

      try {
        const grant = await deps.fetchGrant();
        const sha256 = await deps.hashFile(file);

        handleRef.current = await deps.startTusUpload(file, {
          endpoint: grant.tusEndpoint,
          ownerId: grant.ownerId,
          sha256,
          onProgress: (sent, total) => {
            const pct = total > 0 ? Math.round((sent / total) * 100) : 0;
            setProgress(pct);
          },
          onSuccess: () => {
            setProgress(100);
            setStatus('done');
          },
          onError: (uploadError) => {
            setError(toMessage(uploadError));
            setStatus('error');
          },
        });

        setStatus('uploading');
      } catch (caught) {
        setError(toMessage(caught));
        setStatus('error');
      }
    },
    [deps],
  );

  return { status, progress, error, flip };
}
