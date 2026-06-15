import Link from 'next/link';
import { AnimatedHeading } from '@/components/ui/AnimatedHeading';

// Closer / CTA on the ink ground (docs/design-reference/swiss-pop.html): the last
// push to start a free ranked batch.

export function Closer() {
  return (
    <section
      aria-labelledby="closer-h"
      className="bg-[var(--foreground)] py-[clamp(4rem,3rem+5vw,8rem)] text-[var(--background)]"
    >
      <div className="mx-auto w-full max-w-[1600px] px-[var(--space-margin)]">
        <div className="grid grid-cols-12 items-end gap-[var(--space-gutter)]">
          <h2
            id="closer-h"
            className="col-span-12 font-[family-name:var(--font-grotesk)] font-black leading-[0.9] tracking-[-0.035em] md:col-span-9"
            style={{ fontSize: 'clamp(2.4rem, 1rem + 6vw, 7rem)' }}
          >
            <AnimatedHeading
              text="Хватит листать. Пора зарабатывать."
              accentIndices={[3]}
            />
          </h2>

          <Link
            href="/sign-up"
            data-reveal="rise"
            className="col-span-12 mt-8 inline-flex w-max items-center gap-3 bg-[var(--pop)] px-6 py-4 font-bold text-[var(--on-pop-solid)] transition-colors duration-300 hover:bg-[var(--pop-press)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--pop)] md:col-span-5 md:mt-12"
            style={{ fontSize: '1.1rem' }}
          >
            Загрузить видео
            <span aria-hidden>→</span>
          </Link>
        </div>
      </div>
    </section>
  );
}
