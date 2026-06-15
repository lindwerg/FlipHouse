import Link from 'next/link';

// Colophon-style footer (docs/design-reference/swiss-pop.html): wordmark + tagline,
// three link columns and a typographic base line. Renders the page <footer> landmark.

type FooterColumn = {
  heading: string;
  label: string;
  links: readonly { href: string; text: string }[];
};

const COLUMNS: readonly FooterColumn[] = [
  {
    heading: 'Продукт',
    label: 'Продукт',
    links: [
      { href: '#batch', text: 'Нарезка' },
      { href: '#process', text: 'Как это работает' },
      { href: '#marketplace', text: 'Маркетплейс' },
      { href: '#pricing', text: 'Тарифы' },
    ],
  },
  {
    heading: 'Кому это',
    label: 'Аудитории',
    links: [
      { href: '#marketplace', text: 'Креаторам' },
      { href: '#marketplace', text: 'Рекламодателям' },
      { href: '#process', text: 'Агентствам' },
      { href: '#top', text: 'Подкастерам' },
    ],
  },
  {
    heading: 'Компания',
    label: 'Компания',
    links: [
      { href: '#top', text: 'О нас' },
      { href: '#top', text: 'Вакансии' },
      { href: '#top', text: 'Приватность' },
      { href: '#top', text: 'Условия' },
    ],
  },
];

export function SiteFooter() {
  return (
    <footer className="bg-[var(--background)] py-[clamp(2.4rem,2rem+2vw,4rem)]">
      <div className="mx-auto w-full max-w-[1600px] px-[var(--space-margin)]">
        <div className="grid grid-cols-12 gap-x-[var(--space-gutter)] gap-y-8 border-t-[1.5px] border-[var(--rule-strong)] pt-8">
          <div className="col-span-12 md:col-span-4">
            <Link
              href="/"
              className="mb-3 flex items-center gap-2 font-[family-name:var(--font-grotesk)] text-lg font-extrabold tracking-tight text-[var(--foreground)]"
            >
              <span
                aria-hidden
                className="inline-grid size-6 place-items-center bg-[var(--pop)] font-mono text-[0.7rem] text-[var(--on-pop)]"
              >
                F
              </span>
              FlipHouse
            </Link>
            <p className="max-w-[32ch] font-[family-name:var(--font-narrow)] leading-snug text-[var(--ink-soft)]">
              Одно видео на входе. Пачка вертикальных шортсов на выходе — и
              маркетплейс, который платит клипу.
            </p>
          </div>

          {COLUMNS.map(column => (
            <nav
              key={column.heading}
              aria-label={column.label}
              className="col-span-6 md:col-span-2"
            >
              <h5 className="mb-4 font-mono text-[0.72rem] uppercase tracking-[0.14em] text-[var(--ink-faint)]">
                {column.heading}
              </h5>
              <ul className="m-0 list-none p-0">
                {column.links.map(link => (
                  <li key={link.text} className="mb-2">
                    <a
                      href={link.href}
                      className="font-[family-name:var(--font-narrow)] font-semibold text-[var(--ink-soft)] transition-colors duration-300 hover:text-[var(--pop)]"
                    >
                      {link.text}
                    </a>
                  </li>
                ))}
              </ul>
            </nav>
          ))}
        </div>

        <div className="mt-10 flex flex-wrap justify-between gap-4 border-t border-[var(--rule)] pt-5 font-mono text-[0.74rem] tracking-wide text-[var(--ink-faint)]">
          <span>© 2026 FlipHouse Labs — собрано на 12-колоночной сетке.</span>
          <span>Archivo · IBM Plex Mono — выключка влево.</span>
        </div>
      </div>
    </footer>
  );
}
