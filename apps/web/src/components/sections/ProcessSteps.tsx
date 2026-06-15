import { SectionHead } from './SectionHead';

// Section 02 — the four automatic passes (docs/design-reference/swiss-pop.html):
// find moments → reframe vertical → burn captions → rank & deliver.

type Step = { n: string; t: string; d: string };

const STEPS: readonly Step[] = [
  {
    n: 'ПРОХОД 01',
    t: 'Найти моменты',
    d: 'Транскрипт, энергия звука и модель удержания находят сегменты, которые реально залетают — не случайные нарезки.',
  },
  {
    n: 'ПРОХОД 02',
    t: 'Реврейм в вертикаль',
    d: 'Speaker-tracking держит нужное лицо в кадре, пересобирая 16:9 в чистый 9:16.',
  },
  {
    n: 'ПРОХОД 03',
    t: 'Прожечь субтитры',
    d: 'Karaoke-субтитры по словам в стиле бренда, вшитые в клип и редактируемые до экспорта.',
  },
  {
    n: 'ПРОХОД 04',
    t: 'Ранжировать и отдать',
    d: 'Каждый клип получает скор виральности — публикуй сильное первым, плюс опциональный нативный рекламный слот.',
  },
];

export function ProcessSteps() {
  return (
    <section
      id="process"
      aria-labelledby="process-h"
      className="border-b border-[var(--rule)] py-[var(--space-section)]"
    >
      <div className="mx-auto w-full max-w-[1600px] px-[var(--space-margin)]">
        <SectionHead
          num="02"
          id="process-h"
          title="Четыре прохода, полностью автоматически."
          aside="От двухчасовой загрузки до готовых шортсов за один прогон."
        />

        <ol className="grid grid-cols-1 border-t border-[var(--rule)] sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map(step => (
            <li
              key={step.n}
              className="border-b border-[var(--rule)] py-6 pr-6 lg:border-r lg:last:border-r-0"
            >
              <span className="mb-10 block font-mono text-sm font-semibold tracking-wide text-[var(--pop)] lg:mb-16">
                {step.n}
              </span>
              <h3
                className="mb-2 font-[family-name:var(--font-grotesk)] text-xl font-extrabold leading-tight tracking-tight md:text-2xl"
              >
                {step.t}
              </h3>
              <p className="max-w-[30ch] font-[family-name:var(--font-narrow)] leading-snug text-[var(--ink-soft)]">
                {step.d}
              </p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
