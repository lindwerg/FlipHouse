'use client';

import { useState } from 'react';
import type { FlipPayload, UploadPhase } from '@/components/hero/HeroDropzone';
import { HeroDropzone } from '@/components/hero/HeroDropzone';
import { ResultsView } from '@/features/results/ResultsView';
import type { IngestStatus } from './useUrlIngest';
import { useUrlIngest } from './useUrlIngest';
import { useVideoUpload } from './useVideoUpload';

// Live creator upload surface (P2.2/P2.3). Mounted inside the auth-gated dashboard
// where Clerk is available, it now owns BOTH ingestion paths:
//  - File: grant → browser content-hash → resumable tus upload (useVideoUpload).
//  - URL : POST the pasted link to /api/uploads/ingest, which enqueues a SERVER
//    yt-dlp download into the SAME render pipeline (useUrlIngest).
// onFlip routes a File to the upload hook and a URL to the ingest hook. The
// dropzone's status/error reflect whichever path the last submit used; for a
// finished file upload the results dashboard mounts inline below (the URL path
// has no in-session contentHash — its clips appear in the owner-wide history once
// the worker publishes).

/** Which path the most recent submit took — drives whose status the dropzone shows. */
type ActivePath = 'none' | 'file' | 'url';

/** Map the URL-ingest machine onto the dropzone's phase vocabulary (no byte bar). */
const INGEST_TO_PHASE: Record<IngestStatus, UploadPhase> = {
  idle: 'idle',
  submitting: 'hashing',
  queued: 'done',
  error: 'error',
};

/** Link-specific status captions (the file path's "отпечаток" copy makes no sense for a URL). */
const INGEST_LABEL: Record<IngestStatus, string | null> = {
  idle: null,
  submitting: 'Принимаем ссылку…',
  queued: 'Видео принято в работу',
  error: null,
};

export function CreatorUploadPanel() {
  const upload = useVideoUpload();
  const ingest = useUrlIngest();
  const [activePath, setActivePath] = useState<ActivePath>('none');

  const handleFlip = (payload: FlipPayload): void => {
    if (payload.file) {
      setActivePath('file');
      void upload.flip(payload.file);
      return;
    }
    if (payload.url) {
      setActivePath('url');
      void ingest.submit(payload.url);
    }
  };

  // The dropzone reflects the active path. The URL-ingest path takes over only
  // after a link submit; the file path is the default (so an externally-driven
  // file upload phase/error still surfaces before any in-component interaction).
  const isUrlPath = activePath === 'url';
  const dropzoneStatus = isUrlPath ? INGEST_TO_PHASE[ingest.status] : upload.status;
  const dropzoneError = isUrlPath ? ingest.error : upload.error;
  const dropzoneLabel = isUrlPath ? INGEST_LABEL[ingest.status] : undefined;

  return (
    <div data-slot="creator-upload-panel" className="mt-10 max-w-[760px]">
      <HeroDropzone
        onFlip={handleFlip}
        uploadStatus={dropzoneStatus}
        progress={upload.progress}
        uploadError={dropzoneError}
        statusLabel={dropzoneLabel}
      />
      {upload.contentHash !== null
        ? <ResultsView contentHash={upload.contentHash} />
        : null}
    </div>
  );
}
