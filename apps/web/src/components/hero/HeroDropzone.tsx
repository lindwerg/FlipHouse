'use client';

// Hero dropzone — the central product UX (docs/02 §3.2). One Swiss-styled box
// takes a video FILE (drag&drop on the box, or globalDrop anywhere on the hero
// region) OR a pasted video LINK, tracks status ready→submitted→streaming/error,
// validates type/size, and emits onFlip({file?, url?}). No glass/mesh/BorderBeam
// (checkpoint B) — it composes the P1.6 primitives on a paper panel.

import { FileVideoIcon, LinkIcon } from 'lucide-react';
import type { DragEvent, FormEvent } from 'react';
import { useEffect, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import { cn } from '@/utils/Helpers';
import { isVideoUrl } from '@/utils/isVideoUrl';
import { Dropzone, DropzoneEmptyState } from './dropzone';
import {
  PromptInput,
  type PromptInputStatus,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputToolbar,
} from './prompt-input';

const MAX_SIZE = 500 * 1024 * 1024;
const VALIDATION_ERROR = 'Нужен видеофайл до 500 МБ';
const EMPTY_SUBMIT_ERROR = 'Добавьте видеофайл или ссылку на видео';

export type FlipPayload = { file?: File; url?: string };

// External upload phases the panel can drive (P2.2). When `uploadStatus` is
// provided the dropzone reflects the live grant→hash→upload pipeline: the submit
// icon spins, a progress bar appears, and `uploadError` is surfaced as the
// role=alert. When it is omitted the dropzone keeps its standalone
// ready→submitted→streaming behaviour (design-preview, existing tests).
export type UploadPhase = 'idle' | 'hashing' | 'uploading' | 'done' | 'error';

export type HeroDropzoneProps = {
  onFlip?: (payload: FlipPayload) => void;
  maxSize?: number;
  uploadStatus?: UploadPhase;
  progress?: number;
  uploadError?: string | null;
};

// Map the upload pipeline phase onto the prompt-input's status vocabulary so the
// submit control's icon (spinner / error) reflects real upload state.
const PHASE_TO_PROMPT_STATUS: Record<UploadPhase, PromptInputStatus> = {
  idle: 'ready',
  hashing: 'submitted',
  uploading: 'streaming',
  done: 'streaming',
  error: 'error',
};

const PHASE_LABEL: Record<UploadPhase, string | null> = {
  idle: null,
  hashing: 'Считаем отпечаток видео…',
  uploading: 'Загружаем…',
  done: 'Готово',
  error: null,
};

export function HeroDropzone({
  onFlip,
  maxSize = MAX_SIZE,
  uploadStatus,
  progress,
  uploadError,
}: HeroDropzoneProps) {
  const [files, setFiles] = useState<File[]>([]);
  const [link, setLink] = useState('');
  const [status, setStatus] = useState<PromptInputStatus>('ready');
  const [error, setError] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);
  const reduced = useReducedMotion();

  useEffect(() => {
    setMounted(true);
  }, []);

  const handleDrop = (accepted: File[]) => {
    const file = accepted.at(0);
    if (!file) {
      return;
    }
    setFiles([file]);
    setStatus('ready');
    setError(null);
  };

  const handleError = () => {
    setStatus('error');
    setError(VALIDATION_ERROR);
  };

  const routeFiles = (list: FileList | null) => {
    const file = list?.[0];
    if (!file) {
      return;
    }
    if (file.type.startsWith('video/') && file.size <= maxSize) {
      handleDrop([file]);
    } else {
      handleError();
    }
  };

  const onRegionDrop = (event: DragEvent<HTMLElement>) => {
    if (!event.dataTransfer?.types.includes('Files')) {
      return;
    }
    event.preventDefault();
    routeFiles(event.dataTransfer.files);
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const hasFile = files.length > 0;
    const validLink = isVideoUrl(link);

    if (!hasFile && !validLink) {
      setStatus('error');
      setError(EMPTY_SUBMIT_ERROR);
      return;
    }

    const payload: FlipPayload = {};
    if (hasFile) {
      payload.file = files[0];
    }
    if (validLink) {
      payload.url = link;
    }

    setError(null);
    setStatus('submitted');
    onFlip?.(payload);
    setTimeout(() => setStatus('streaming'), 0);
  };

  const animate = !reduced;
  const linkIsValid = isVideoUrl(link);

  // External upload phase (when controlled) wins over the standalone status so
  // the submit icon + section data-status track the real pipeline. Absent the
  // prop, behaviour is unchanged.
  const isControlled = uploadStatus !== undefined;
  const resolvedStatus: PromptInputStatus = isControlled
    ? PHASE_TO_PROMPT_STATUS[uploadStatus]
    : status;
  const phaseLabel = isControlled ? PHASE_LABEL[uploadStatus] : null;
  const isUploading = uploadStatus === 'uploading';
  const alertMessage = (isControlled ? uploadError : null) ?? error;

  return (
    <section
      aria-label="Загрузка видео"
      data-slot="hero-dropzone"
      data-status={resolvedStatus}
      data-animate={animate ? true : undefined}
      onDrop={onRegionDrop}
      onDragOver={event => event.preventDefault()}
      className={cn(
        'flex flex-col gap-4 transition-[opacity,transform] duration-500 ease-[var(--ease-out-expo)] motion-reduce:transition-none',
        animate && !mounted ? 'translate-y-2 opacity-0' : 'translate-y-0 opacity-100',
      )}
    >
      {/* One Swiss .dropbar box (docs/design-reference/swiss-pop.html): the drop
          field and the link/submit row share a single --rule-strong border with
          a hairline divide between them, instead of two separate boxes. */}
      <div
        data-slot="dropbar"
        className="flex flex-col divide-y divide-[var(--rule)] border-[1.5px] border-[var(--rule-strong)] bg-[var(--background)]"
      >
        <Dropzone
          accept={{ 'video/*': [] }}
          maxFiles={1}
          maxSize={maxSize}
          onDrop={handleDrop}
          onError={handleError}
          className="border-0 bg-transparent p-6"
        >
          <DropzoneEmptyState />
        </Dropzone>

        <PromptInput onSubmit={handleSubmit} className="border-0 bg-transparent">
          <PromptInputTextarea
            aria-label="Ссылка на видео"
            placeholder="…или вставьте ссылку на видео (YouTube, Vimeo, .mp4)"
            rows={2}
            value={link}
            onChange={event => setLink(event.target.value)}
          />
          <PromptInputToolbar>
            <div className="mr-auto flex flex-wrap items-center gap-2">
              {files[0] && (
                <Badge data-slot="file-chip" variant="outline">
                  <FileVideoIcon aria-hidden size={12} />
                  {files[0].name}
                </Badge>
              )}
              {linkIsValid && (
                <Badge data-slot="link-chip" variant="outline">
                  <LinkIcon aria-hidden size={12} />
                  {link}
                </Badge>
              )}
            </div>
            <PromptInputSubmit aria-label="Отправить видео на нарезку" status={resolvedStatus} />
          </PromptInputToolbar>
        </PromptInput>
      </div>

      {phaseLabel && (
        <div data-slot="upload-progress" className="flex flex-col gap-1">
          <p className="font-mono text-[0.72rem] uppercase tracking-[0.16em] text-[var(--ink-soft)]">
            {phaseLabel}
          </p>
          {isUploading && (
            <div
              role="progressbar"
              aria-label="Прогресс загрузки"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={progress ?? 0}
              className="h-[3px] w-full bg-[var(--rule)]"
            >
              <div
                data-slot="upload-progress-fill"
                className="h-full origin-left bg-[var(--pop)] transition-transform duration-300 ease-[var(--ease-out-expo)] motion-reduce:transition-none"
                style={{ transform: `scaleX(${(progress ?? 0) / 100})` }}
              />
            </div>
          )}
        </div>
      )}

      {alertMessage && (
        <p
          role="alert"
          className="font-mono text-[0.72rem] uppercase tracking-[0.16em] text-[var(--pop)]"
        >
          {alertMessage}
        </p>
      )}
    </section>
  );
}
