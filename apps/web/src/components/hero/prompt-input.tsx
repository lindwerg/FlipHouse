'use client';

// Swiss prompt-input primitive family. Custom (not ai-elements) per checkpoint B:
// a hairline-bordered paper field with a grotesk textarea and a vermillion submit
// whose icon reflects the flip status. The API surface (PromptInput /
// PromptInputTextarea / PromptInputToolbar / PromptInputSubmit status=...) is the
// one composed by the hero dropzone in P1.7. Reference: .dropbar in
// docs/design-reference/swiss-pop.html.

import { AlertCircleIcon, ArrowUpIcon, LoaderCircleIcon } from 'lucide-react';
import type { ComponentProps, ReactNode } from 'react';
import { cn } from '@/utils/Helpers';

export type PromptInputStatus = 'ready' | 'submitted' | 'streaming' | 'error';

export type PromptInputProps = ComponentProps<'form'>;

export function PromptInput({ className, children, ...props }: PromptInputProps) {
  return (
    <form
      data-slot="prompt-input"
      className={cn(
        'flex flex-col border-[1.5px] border-[var(--rule-strong)] bg-[var(--background)]',
        className,
      )}
      {...props}
    >
      {children}
    </form>
  );
}

export type PromptInputTextareaProps = ComponentProps<'textarea'>;

export function PromptInputTextarea({ className, ...props }: PromptInputTextareaProps) {
  return (
    <textarea
      data-slot="prompt-input-textarea"
      className={cn(
        'w-full resize-none bg-transparent px-[var(--space-gutter)] py-3 font-[family-name:var(--font-grotesk)] text-[var(--foreground)] outline-none placeholder:text-[var(--ink-faint)]',
        'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--pop)]',
        className,
      )}
      {...props}
    />
  );
}

export type PromptInputToolbarProps = ComponentProps<'div'>;

export function PromptInputToolbar({ className, children, ...props }: PromptInputToolbarProps) {
  return (
    <div
      data-slot="prompt-input-toolbar"
      className={cn(
        'flex items-center justify-end border-t border-[var(--rule)] p-2',
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

const STATUS_ICON: Record<PromptInputStatus, ReactNode> = {
  ready: <ArrowUpIcon size={16} />,
  submitted: <LoaderCircleIcon className="animate-spin" size={16} />,
  streaming: <LoaderCircleIcon className="animate-spin" size={16} />,
  error: <AlertCircleIcon size={16} />,
};

export type PromptInputSubmitProps = ComponentProps<'button'> & {
  status?: PromptInputStatus;
};

export function PromptInputSubmit({
  status = 'ready',
  className,
  children,
  ...props
}: PromptInputSubmitProps) {
  return (
    <button
      type="submit"
      data-slot="prompt-input-submit"
      className={cn(
        'inline-flex items-center justify-center gap-2 bg-[var(--pop)] px-4 py-2 font-mono text-sm font-bold text-[var(--on-pop-solid)] transition-colors duration-200',
        'hover:bg-[var(--pop-press)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--pop)]',
        'disabled:cursor-not-allowed disabled:opacity-60',
        className,
      )}
      {...props}
    >
      {children ?? STATUS_ICON[status]}
    </button>
  );
}
