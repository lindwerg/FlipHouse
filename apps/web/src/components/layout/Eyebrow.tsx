import type { ReactNode } from 'react';

type EyebrowProps = {
  children: ReactNode;
  className?: string;
};

/**
 * Swiss-style kicker label: a small, mono, letter-spaced uppercase tag used above
 * section headings (e.g. "01 — The output" / "From the cut"). Reference:
 * docs/design-reference/swiss-pop.html.
 */
export function Eyebrow({ children, className }: EyebrowProps) {
  return (
    <p
      data-slot="eyebrow"
      className={[
        'font-mono text-[0.72rem] uppercase tracking-[0.18em] text-[var(--ink-faint)]',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      {children}
    </p>
  );
}
