import { SectionHead } from './SectionHead';

// Section 04 — receipts: big numbers under the product (docs/design-reference/swiss-pop.html).

type Stat = { n: string; u: string; l: string };

const STATS: readonly Stat[] = [
  { n: '12', u: '×', l: 'Шортсов из одной длинной загрузки в среднем.' },
  { n: '9:16', u: '', l: 'Speaker-tracked вертикальный реврейм на каждом клипе, автоматически.' },
  { n: '94', u: '%', l: 'Точность тайминга субтитров, по словам и полностью редактируемая.' },
  { n: '$0', u: '↑', l: 'Старт бесплатно; добавь маркетплейс, чтобы зарабатывать на том, что уже постишь.' },
];

export function Metrics() {
  return (
    <section
      id="pricing"
      aria-labelledby="stats-h"
      className="border-b border-[var(--rule)] py-[var(--space-section)]"
    >
      <div className="mx-auto w-full max-w-[1600px] px-[var(--space-margin)]">
        <SectionHead
          num="04"
          id="stats-h"
          title="Сделано для объёма, цена — за объём."
          aside="Одна загрузка — неделя шортсов, и строка выручки под каждым."
        />

        <div className="grid grid-cols-1 border-t-[1.5px] border-[var(--rule-strong)] sm:grid-cols-2 lg:grid-cols-4">
          {STATS.map(stat => (
            <div
              key={stat.l}
              className="border-b border-[var(--rule)] pt-6 pb-6 pr-6 lg:border-r lg:pb-0 lg:last:border-r-0"
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
