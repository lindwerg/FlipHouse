'use client';

// Swiss-restyled drop surface. The engine is lifted from Kibo UI Dropzone
// (MIT — vendor/kibo/packages/dropzone), a thin react-dropzone wrapper, and
// re-skinned to the Swiss Pop reference (docs/design-reference/swiss-pop.html):
// a hairline-bordered paper field, a vermillion drag-active outline and mono
// Russian copy. No glass / BorderBeam / AI-prompt-box (per checkpoint B). The
// kibo context API (DropzoneEmptyState reads limits from context) is preserved
// so the hero composition in P1.7 can use it — and add DropzoneContent — as-is.

import { UploadIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { createContext, useContext } from 'react';
import type { DropEvent, DropzoneOptions, FileRejection } from 'react-dropzone';
import { useDropzone } from 'react-dropzone';
import { cn } from '@/utils/Helpers';

type DropzoneContextValue = {
  src?: File[];
  accept?: DropzoneOptions['accept'];
  maxSize?: DropzoneOptions['maxSize'];
  minSize?: DropzoneOptions['minSize'];
  maxFiles?: DropzoneOptions['maxFiles'];
};

const BYTE_UNITS = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ', 'ПБ'] as const;

const renderBytes = (bytes: number): string => {
  let size = bytes;
  let unitIndex = 0;

  while (size >= 1024 && unitIndex < BYTE_UNITS.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }

  const value = Number.isInteger(size) ? size.toString() : size.toFixed(1);

  return `${value} ${BYTE_UNITS[unitIndex]}`;
};

const DropzoneContext = createContext<DropzoneContextValue | undefined>(undefined);

const useDropzoneContext = (): DropzoneContextValue => {
  const context = useContext(DropzoneContext);

  if (!context) {
    throw new Error('useDropzoneContext must be used within a Dropzone');
  }

  return context;
};

export type DropzoneProps = Omit<DropzoneOptions, 'onDrop'> & {
  src?: File[];
  className?: string;
  onDrop?: (
    acceptedFiles: File[],
    fileRejections: FileRejection[],
    event: DropEvent,
  ) => void;
  children?: ReactNode;
};

export function Dropzone({
  accept,
  maxFiles = 1,
  maxSize,
  minSize,
  onDrop,
  onError,
  disabled,
  src,
  className,
  children,
  ...props
}: DropzoneProps) {
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept,
    maxFiles,
    maxSize,
    minSize,
    onError,
    disabled,
    onDrop: (acceptedFiles, fileRejections, event) => {
      if (fileRejections.length > 0) {
        const message = fileRejections.at(0)?.errors.at(0)?.message;
        onError?.(new Error(message));

        return;
      }

      onDrop?.(acceptedFiles, fileRejections, event);
    },
    ...props,
  });

  return (
    <DropzoneContext.Provider
      key={JSON.stringify(src)}
      value={{ src, accept, maxSize, minSize, maxFiles }}
    >
      <button
        {...getRootProps()}
        // react-dropzone forces role="presentation"; reset it so the native
        // button role (and a11y) is preserved on this drop field.
        role={undefined}
        type="button"
        data-slot="dropzone"
        data-drag-active={isDragActive || undefined}
        disabled={disabled}
        className={cn(
          'flex w-full flex-col items-center justify-center gap-3 border-[1.5px] border-[var(--rule-strong)] bg-[var(--background)] p-8 text-center transition-[outline-color] duration-200',
          'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--pop)]',
          isDragActive && 'outline-2 outline-[var(--pop)]',
          disabled && 'cursor-not-allowed opacity-60',
          className,
        )}
      >
        <input {...getInputProps()} disabled={disabled} />
        {children}
      </button>
    </DropzoneContext.Provider>
  );
}

export type DropzoneEmptyStateProps = {
  children?: ReactNode;
  className?: string;
};

export function DropzoneEmptyState({ children, className }: DropzoneEmptyStateProps) {
  const { src, maxSize, maxFiles } = useDropzoneContext();

  if (src) {
    return null;
  }

  if (children) {
    return <>{children}</>;
  }

  const limits: string[] = [maxFiles === 1 ? 'до 1 файла' : `до ${maxFiles} файлов`];

  if (maxSize) {
    limits.push(`до ${renderBytes(maxSize)}`);
  }

  return (
    <span
      data-slot="dropzone-empty"
      className={cn('flex flex-col items-center justify-center gap-2', className)}
    >
      <UploadIcon aria-hidden className="text-[var(--ink-faint)]" size={20} />
      <span className="block font-[family-name:var(--font-grotesk)] text-sm font-semibold text-[var(--foreground)]">
        Перетащите видео или нажмите, чтобы выбрать
      </span>
      <span className="block font-mono text-[0.72rem] uppercase tracking-[0.16em] text-[var(--ink-faint)]">
        {limits.join(' · ')}
      </span>
    </span>
  );
}
