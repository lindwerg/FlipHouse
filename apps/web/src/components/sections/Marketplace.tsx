import { SectionHead } from './SectionHead';

// Section 03 — the marketplace (docs/design-reference/swiss-pop.html): advertiser
// offers become native banners inside real creator clips; creators get paid per
// view and per conversion. Demo is a 9:16 clip region with a payout ledger — no
// phone mockup.

type Ledger = { label: string; value: string; payout?: boolean };

const LEDGER: readonly Ledger[] = [
  { label: 'Рекламодатель', value: 'ShipFast' },
  { label: 'Ставка', value: '$14 CPM + $6/конв' },
  { label: 'Показы', value: '412 907' },
  { label: 'Конверсии', value: '318' },
  { label: 'Выплата креатору', value: '$7 689', payout: true },
];

export function Marketplace() {
  return (
    <section
      id="marketplace"
      aria-labelledby="market-h"
      className="border-b-[1.5px] border-[var(--rule-strong)] py-[var(--space-section)]"
    >
      <div className="mx-auto w-full max-w-[1600px] px-[var(--space-margin)]">
        <SectionHead
          num="03"
          id="market-h"
          title="Маркетплейс, который платит клипу, а не питчу."
          aside="Офферы рекламодателей становятся нативными баннерами внутри реальных клипов."
        />

        <div className="grid grid-cols-12 gap-[var(--space-gutter)] gap-y-10">
          <div className="col-span-12 md:col-span-5">
            <p
              className="mb-6 max-w-[38ch] leading-snug text-[var(--ink-soft)]"
              style={{ fontSize: 'var(--text-base)' }}
            >
              Рекламодатели публикуют оффер. FlipHouse матчит его с клипами, где он
              уместен, и встраивает как
              {' '}
              <b className="font-bold text-[var(--foreground)]">нативный баннер</b>
              {' '}
              — по размеру, времени и месту так, что он читается частью шортса.
              {' '}
              <b className="font-bold text-[var(--foreground)]">Креаторы получают оплату за показы и конверсии.</b>
              {' '}
              Без DM, медиакитов и догадок по флэт-фи.
            </p>

            <div className="grid grid-cols-1 border-t-[1.5px] border-[var(--rule-strong)] sm:grid-cols-2">
              <div className="border-b border-[var(--rule)] py-4 pr-4 sm:border-r">
                <h4 className="mb-1 font-mono text-[0.72rem] uppercase tracking-[0.14em] text-[var(--pop)]">
                  Для креаторов
                </h4>
                <p className="font-[family-name:var(--font-narrow)] leading-snug text-[var(--ink-soft)]">
                  Превратите старые клипы в инвентарь. Принимайте офферы, которые
                  нравятся, держите редакторский контроль, получайте оплату за
                  результат.
                </p>
              </div>
              <div className="border-b border-[var(--rule)] py-4 sm:pl-4">
                <h4 className="mb-1 font-mono text-[0.72rem] uppercase tracking-[0.14em] text-[var(--cobalt)]">
                  Для рекламодателей
                </h4>
                <p className="font-[family-name:var(--font-narrow)] leading-snug text-[var(--ink-soft)]">
                  Покупайте размещения внутри ранжированных тематических шортсов.
                  Платите за видимые показы и конверсии, а не за неуловимые
                  impressions.
                </p>
              </div>
            </div>
          </div>

          <figure
            className="col-span-12 border-[1.5px] border-[var(--rule-strong)] bg-[var(--foreground)] p-6 text-[var(--background)] md:col-span-6 md:col-start-7"
            aria-label="Клип креатора с нативным баннером рекламодателя и выплатой"
          >
            <div className="mb-5 flex items-baseline justify-between border-b border-[color-mix(in_oklch,var(--background)_22%,transparent)] pb-3">
              <span className="font-mono text-[0.72rem] uppercase tracking-[0.14em] text-[color-mix(in_oklch,var(--background)_70%,transparent)]">
                Клип #01 · нативное размещение
              </span>
              <span className="inline-flex items-center gap-1.5 font-mono text-[0.72rem] tracking-wide text-[var(--pop)]">
                <span aria-hidden className="size-1.5 rounded-full bg-[var(--pop)]" />
                ИДЁТ ОТКРУТКА
              </span>
            </div>

            <div className="grid grid-cols-[6rem_1fr] items-stretch gap-5 md:grid-cols-[7.2rem_1fr]">
              <div
                aria-hidden
                className="flex aspect-[9/16] flex-col justify-between border border-[color-mix(in_oklch,var(--background)_30%,transparent)] p-2"
              >
                <span className="font-mono text-[0.6rem] tracking-widest text-[color-mix(in_oklch,var(--background)_60%,transparent)]">
                  9 : 16
                </span>
                <div className="text-center font-[family-name:var(--font-grotesk)] text-[0.74rem] font-extrabold uppercase leading-[1.1] tracking-tight">
                  НИКТО НЕ
                  {' '}
                  <span className="text-[var(--pop)]">ПРИДЁТ</span>
                  {' '}
                  СПАСАТЬ ТВОЙ ЗАПУСК
                </div>
                <div className="rounded-sm border-[1.5px] border-[var(--pop)] bg-[color-mix(in_srgb,var(--pop)_26%,var(--foreground))] p-1 text-center font-mono text-[0.58rem] leading-tight tracking-wide">
                  SHIPFAST · ДЕПЛОЙ В 1 КЛИК
                  <br />
                  FLIP20 → −20%
                </div>
              </div>

              <div className="flex flex-col gap-2">
                {LEDGER.map(row => (
                  <div
                    key={row.label}
                    className="grid grid-cols-[1fr_auto] items-baseline gap-2 border-b border-[color-mix(in_oklch,var(--background)_16%,transparent)] pb-2 font-mono text-sm"
                  >
                    <span className="tracking-wide text-[color-mix(in_oklch,var(--background)_70%,transparent)]">
                      {row.label}
                    </span>
                    <span
                      className={`font-semibold tabular-nums ${row.payout ? 'text-base text-[var(--pop)]' : ''}`}
                    >
                      {row.value}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <figcaption className="mt-5 border-t border-[color-mix(in_oklch,var(--background)_22%,transparent)] pt-4 font-[family-name:var(--font-narrow)] text-sm text-[color-mix(in_oklch,var(--background)_78%,transparent)]">
              Баннер живёт внутри клипа — не пре-ролл и не прерывание. Читаемый, в
              стиле бренда, с оплатой за результат.
            </figcaption>
          </figure>
        </div>
      </div>
    </section>
  );
}
