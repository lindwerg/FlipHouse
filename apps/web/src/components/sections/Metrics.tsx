import { SectionHead } from './SectionHead';

// Section 04 — receipts: big numbers under the product (docs/design-reference/swiss-pop.html).

type Stat = { n: string; u: string; l: string };

const STATS: readonly Stat[] = [
  { n: '12', u: '×', l: 'Шортсов из одной длинной загрузки в среднем.' },
  { n: '9:16', u: '', l: 'Вертикальный кадр 9:16 с удержанием спикера, автоматически.' },
  { n: '94', u: '%', l: 'Точность тайминга субтитров по словам. Полностью редактируемых.' },
  { n: '$0', u: '↑', l: 'Старт бесплатно. Добавьте маркетплейс и зарабатывайте на том, что уже публикуете.' },
];

export function Metrics() {
  return (
    <section
      id="pricing"
      aria-labelledby="stats-h"
      className="min-h-svh border-b-[1.5px] border-[var(--rule-strong)] py-[var(--space-section)]"
    >
      <div className="mx-auto w-full max-w-[1600px] px-[var(--space-margin)]">
        <SectionHead
          num="04"
          id="stats-h"
          title="Сделано для объёма. Цена тоже за объём."
          aside="Одна загрузка даёт неделю шортсов. Под каждым клипом строка выручки."
        />

        <div data-reveal-group="rise" className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
          {STATS.map(stat => (
            <div
              key={stat.l}
              data-reveal-item
              className="border-b border-[var(--rule)] py-6 pr-6 md:py-8 lg:border-r lg:px-6 lg:first:pl-0 lg:last:border-r-0"
            >
              <div
                className="font-[family-name:var(--font-grotesk)] font-black leading-[0.9] tracking-[-0.04em]"
                style={{ fontSize: 'clamp(2.4rem, 1.4rem + 3.6vw, 5rem)' }}
              >
                {stat.n}
                {stat.u && <span className="text-[var(--pop)]">{stat.u}</span>}
              </div>
              <p className="mt-3 max-w-[22ch] font-[family-name:var(--font-narrow)] font-semibold leading-snug text-[var(--ink-soft)]">
                {stat.l}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
