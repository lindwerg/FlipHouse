import { SectionHead } from './SectionHead';

// Section 01: the product shown as a ranked table (docs/design-reference/swiss-pop.html).
// One source video becomes a scored, ordered list of clips ready to publish and earn.

type Clip = {
  rank: string;
  title: string;
  meta: string;
  len: string;
  tag: string;
  score: number;
};

const CLIPS: readonly Clip[] = [
  {
    rank: '01',
    title: '«Никто не придёт спасать твой запуск»',
    meta: '00:41:12 — 00:41:43 · вертикальный кадр за спикером',
    len: '0:31',
    tag: 'Зацепка',
    score: 94,
  },
  {
    rank: '02',
    title: '«Ошибка в цене, которая нас чуть не убила»',
    meta: '01:12:55 — 01:13:38 · субтитры по словам',
    len: '0:43',
    tag: 'История',
    score: 88,
  },
  {
    rank: '03',
    title: '«Вот шаблон холодного письма, по строкам»',
    meta: '00:18:02 — 00:18:49 · пошаговый разбор',
    len: '0:47',
    tag: 'Инструкция',
    score: 82,
  },
  {
    rank: '04',
    title: '«Одна метрика, которую я смотрю каждое утро»',
    meta: '00:54:21 — 00:54:58 · субтитры по словам',
    len: '0:37',
    tag: 'Список',
    score: 79,
  },
  {
    rank: '05',
    title: '«Почему я уволил крупнейшего клиента»',
    meta: '02:03:44 — 02:04:19 · вертикальный кадр за спикером',
    len: '0:35',
    tag: 'Мнение',
    score: 74,
  },
];

const ROW = 'grid grid-cols-[2.5rem_1fr_4rem] items-center gap-3 md:grid-cols-[3.5rem_1fr_7rem_6.5rem_5rem] md:gap-[var(--space-gutter)]';

export function RankedBatch() {
  return (
    <section
      id="batch"
      aria-labelledby="batch-h"
      className="min-h-svh border-b-[1.5px] border-[var(--rule-strong)] py-[var(--space-section)]"
    >
      <div className="mx-auto w-full max-w-[1600px] px-[var(--space-margin)]">
        <SectionHead
          num="01"
          id="batch-h"
          title="Из одного видео получается упорядоченный список клипов с оценкой виральности."
          aside="Каждый клип оценён по зацепке, динамике, удержанию и плотности субтитров. Сверху те, что вероятнее принесут просмотры и доход."
        />

        <div data-reveal-group="rise" role="table" aria-label="Ранжированные клипы из одного видео">
          <div
            role="row"
            className={`${ROW} border-b border-[var(--rule)] pb-2 font-mono text-[0.72rem] uppercase tracking-[0.14em] text-[var(--ink-faint)]`}
          >
            <span role="columnheader">Ранг</span>
            <span role="columnheader">Клип</span>
            <span role="columnheader" className="hidden md:block">Длина</span>
            <span role="columnheader" className="hidden md:block">Формат</span>
            <span role="columnheader" className="text-right">
              <span className="md:hidden">Вир.</span>
              <span className="hidden md:inline">Виральность</span>
            </span>
          </div>

          {CLIPS.map((clip, index) => (
            <div
              key={clip.rank}
              data-reveal-item
              role="row"
              className={`${ROW} border-b border-[var(--rule)] py-4`}
            >
              <span
                role="cell"
                className={`font-mono text-xl font-semibold ${index === 0 ? 'text-[var(--pop)]' : 'text-[var(--foreground)]'}`}
              >
                {clip.rank}
              </span>
              <div role="cell" className="font-bold leading-tight tracking-tight">
                {clip.title}
                <small className="mt-1 block font-mono text-[0.72rem] font-normal tracking-wide text-[var(--ink-faint)]">
                  {clip.meta}
                </small>
              </div>
              <span role="cell" className="hidden font-mono text-sm text-[var(--ink-soft)] md:block">
                {clip.len}
              </span>
              <span role="cell" className="hidden md:block">
                <span className="inline-block rounded-full border border-[var(--rule-strong)] px-2 py-0.5 font-mono text-[0.68rem] uppercase tracking-wide">
                  {clip.tag}
                </span>
              </span>
              <div role="cell" className="text-right tabular-nums">
                <span className="font-mono text-lg font-semibold">{clip.score}</span>
                <span className="mt-1 block h-1 w-full overflow-hidden bg-[var(--rule)]">
                  <span
                    className={`block h-full ${index === 0 ? 'bg-[var(--pop)]' : 'bg-[var(--foreground)]'}`}
                    style={{ width: `${clip.score}%` }}
                  />
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
