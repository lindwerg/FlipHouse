import { Fragment } from 'react';
import { cn } from '@/utils/Helpers';

// Splits a heading into per-word spans (data-slot="word") so a scroll/load
// reveal (P1.9) can stagger them on compositor-only transform/opacity — no motion
// library (checkpoint B). In P1.8 the words render statically; accentIndices tint
// chosen words with the vermillion --pop signal.
export type AnimatedHeadingProps = {
  text: string;
  className?: string;
  accentIndices?: readonly number[];
};

export function AnimatedHeading({
  text,
  className,
  accentIndices = [],
}: AnimatedHeadingProps) {
  const words = text.split(/\s+/).filter(Boolean);
  const accent = new Set(accentIndices);

  return (
    <span data-slot="animated-heading" className={cn('inline', className)}>
      {words.map((word, index) => (
        <Fragment key={`${word}-${index}`}>
          {index > 0 ? ' ' : null}
          <span
            data-slot="word"
            className={cn('inline-block', accent.has(index) && 'text-[var(--pop)]')}
          >
            {word}
          </span>
        </Fragment>
      ))}
    </span>
  );
}
