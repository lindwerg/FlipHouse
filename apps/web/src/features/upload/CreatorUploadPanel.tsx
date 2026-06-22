'use client';

import type { FlipPayload } from '@/components/hero/HeroDropzone';
import { HeroDropzone } from '@/components/hero/HeroDropzone';
import { ResultsView } from '@/features/results/ResultsView';
import { useVideoUpload } from './useVideoUpload';

// Live creator upload surface (P2.2/P2.3). Mounted inside the auth-gated dashboard
// where Clerk is available, it owns the grant→hash→resumable-upload pipeline
// (useVideoUpload) and feeds its phase/progress/error back into the shared
// HeroDropzone so the founder sees real upload state. File-only for now: a pasted
// link has no upload path yet, so onFlip only starts an upload for a File. Once
// the file is hashed (contentHash known), the results dashboard mounts inline
// below the dropzone — no forced navigation for the MVP.

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
