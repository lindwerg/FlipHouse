'use client';

import type { FlipPayload } from '@/components/hero/HeroDropzone';
import { HeroDropzone } from '@/components/hero/HeroDropzone';
import { ResultsView } from '@/features/results/ResultsView';
import { useVideoUpload } from './useVideoUpload';

// Live creator upload surface (P2.2/P2.3). Mounted inside the auth-gated dashboard
// where Clerk is available, it owns the FILE ingestion path: grant → browser
// content-hash → resumable tus upload (useVideoUpload). onFlip routes the selected
// File to the upload hook; the dropzone's status/error reflect the live pipeline,
// and once a file finishes hashing the results dashboard mounts inline below.
//
// The pasted-link path was removed (YouTube blocks our server IP, so server-side
// URL ingest is disabled). A fileless flip is ignored here — HeroDropzone shows
// its own "Добавьте видеофайл" validation alert before it ever reaches this panel.

export function CreatorUploadPanel() {
  const upload = useVideoUpload();

  const handleFlip = (payload: FlipPayload): void => {
    if (payload.file) {
      void upload.flip(payload.file);
    }
  };

  return (
    <div data-slot="creator-upload-panel" className="mt-10 max-w-[760px]">
      <HeroDropzone
        onFlip={handleFlip}
        uploadStatus={upload.status}
        progress={upload.progress}
        uploadError={upload.error}
      />
      {upload.contentHash !== null
        ? <ResultsView contentHash={upload.contentHash} />
        : null}
    </div>
  );
}
