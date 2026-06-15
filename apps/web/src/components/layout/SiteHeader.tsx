import Link from 'next/link';

const NAV_LINKS = [
  { href: '/#nareska', label: 'Нарезка' },
  { href: '/#how-it-works', label: 'Как это работает' },
  { href: '/#marketplace', label: 'Маркетплейс' },
  { href: '/#pricing', label: 'Тарифы' },
] as const;

/**
 * Swiss-style site header: wordmark + hairline-ruled mono nav + a vermillion
 * "Start free" CTA, sitting on a heavy bottom rule. Presentational shell for the
 * landing; routing/i18n wiring lands with the auth steps. Reference:
 * docs/design-reference/swiss-pop.html.
 */
export function SiteHeader() {
  return (
    <header className="border-b-[1.5px] border-[var(--rule-strong)] bg-[var(--background)]">
      <div className="mx-auto flex max-w-[1600px] items-center justify-between px-[var(--space-margin)] py-4">
        <Link
          href="/"
          className="flex items-center gap-2 font-[family-name:var(--font-grotesk)] text-lg font-extrabold tracking-tight text-[var(--foreground)]"
        >
          <span
            aria-hidden
            className="inline-grid size-6 place-items-center bg-[var(--pop)] font-mono text-[0.7rem] text-[var(--on-pop-solid)]"
          >
            F
          </span>
          FlipHouse
        </Link>

        <nav aria-label="Основная навигация" className="flex items-stretch">
          <ul className="hidden items-stretch md:flex">
            {NAV_LINKS.map(link => (
              <li key={link.href} className="flex">
                <Link
                  href={link.href}
                  className="border-l border-[var(--rule)] px-5 py-1 font-[family-name:var(--font-narrow)] text-sm text-[var(--ink-soft)] transition-colors duration-200 hover:text-[var(--foreground)] focus-visible:text-[var(--foreground)] focus-visible:outline-2 focus-visible:outline-[var(--pop)]"
                >
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>

          <Link
            href="/sign-in"
            className="border-l border-[var(--rule)] px-5 py-1 font-[family-name:var(--font-narrow)] text-sm text-[var(--ink-soft)] transition-colors duration-200 hover:text-[var(--foreground)] focus-visible:text-[var(--foreground)] focus-visible:outline-2 focus-visible:outline-[var(--pop)]"
          >
            Войти
          </Link>
          <Link
            href="/sign-up"
            className="ml-0 border-l-[1.5px] border-[var(--rule-strong)] bg-[var(--foreground)] px-5 py-1 font-mono text-sm text-[var(--background)] transition-colors duration-200 hover:bg-[var(--pop)] hover:text-[var(--on-pop-solid)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--pop)]"
          >
            Начать бесплатно →
          </Link>
        </nav>
      </div>
    </header>
  );
}
