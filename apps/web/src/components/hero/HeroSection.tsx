import { Eyebrow } from '@/components/layout/Eyebrow';
import { AnimatedHeading } from '@/components/ui/AnimatedHeading';
import { HeroDropzone } from './HeroDropzone';

// Flush-left Swiss hero (docs/design-reference/swiss-pop.html): signage kickers,
// the single huge --text-hero H1, a lead, the .dropbar (HeroDropzone) and a mono
// note line. Holds the page's only <h1>.

const KICKERS = [
  'FlipHouse // Vol. 01',
  'Видео → ранжированные шортсы',
  'Для креаторов и рекламодателей',
] as const;

export function HeroSection() {
  return (
    <section
      aria-labelledby="hero-h"
      className="border-b-[1.5px] border-[var(--rule-strong)] pb-[var(--space-section)] pt-10"
    >
      <div className="mx-auto w-full max-w-[1600px] px-[var(--space-margin)]">
        <div className="mb-8 flex flex-wrap items-baseline gap-x-6 gap-y-2 border-b border-[var(--rule)] pb-4 md:mb-12">
          {KICKERS.map(kicker => (
            <Eyebrow key={kicker} className="text-[var(--foreground)]">
              {kicker}
            </Eyebrow>
          ))}
        </div>

        <div className="grid grid-cols-12 gap-[var(--space-gutter)]">
          <h1
            id="hero-h"
            className="col-span-12 font-[family-name:var(--font-grotesk)] font-black leading-[0.9] tracking-[-0.035em]"
            style={{ fontSize: 'var(--text-hero)' }}
          >
            <AnimatedHeading
              text="Одно видео. Пачка ранжированных шортсов."
              accentIndices={[3]}
            />
          </h1>

          <p
            className="col-span-12 mt-6 max-w-[36ch] font-medium leading-snug text-[var(--ink-soft)] md:col-start-8 md:col-span-5 md:mt-10"
            style={{ fontSize: 'var(--text-base)' }}
          >
            Загрузите длинное видео. FlipHouse вырезает моменты, которые
            {' '}
            <b className="font-bold text-[var(--foreground)]">залетают</b>
            , переводит их в 9:16 со speaker-tracking, прожигает karaoke-субтитры и
            отдаёт
            {' '}
            <b className="font-bold text-[var(--foreground)]">ранжированными по виральности</b>
            {' '}
            — готовыми к публикации.
          </p>
        </div>

        <div className="mt-8 max-w-[760px] md:mt-12">
          <HeroDropzone />
        </div>

        <p className="mt-4 flex flex-wrap items-center gap-2 font-mono text-[0.74rem] tracking-wide text-[var(--ink-faint)]">
          <span aria-hidden className="text-[var(--pop)]">●</span>
          MP4 · MOV · YouTube · Zoom · Riverside
          <span aria-hidden>—</span>
          до 4 часов
          <span aria-hidden>—</span>
          без карты
        </p>
      </div>
    </section>
  );
}
