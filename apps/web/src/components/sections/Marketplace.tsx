import { SectionHead } from './SectionHead';

// Section 03 — the marketplace (docs/design-reference/swiss-pop.html): advertiser
// offers become native banners inside real creator clips; creators get paid per
// view and per conversion. Demo is a 9:16 clip region with a payout ledger — no
// phone mockup.

type Ledger = { label: string; value: string; payout?: boolean };

const LEDGER: readonly Ledger[] = [
  { label: 'Рекламодатель', value: 'ShipFast' },
  { label: 'Ставка', value: '$14 / 1000 показов + $6 за конверсию' },
  { label: 'Показы', value: '412 907' },
  { label: 'Конверсии', value: '318' },
  { label: 'Выплата автору', value: '$7 689', payout: true },
];

export function Marketplace() {
  return (
    <section
      id="marketplace"
      aria-labelledby="market-h"
      className="min-h-svh border-b-[1.5px] border-[var(--rule-strong)] py-[var(--space-section)]"
    >
      <div className="mx-auto w-full max-w-[1600px] px-[var(--space-margin)]">
        <SectionHead
          num="03"
          id="market-h"
          title="Маркетплейс платит за клип, который уже смотрят."
          aside="Предложения рекламодателей становятся нативными баннерами внутри реальных клипов."
        />

        <div className="grid grid-cols-12 gap-[var(--space-gutter)] gap-y-12">
          <div className="col-span-12 lg:col-span-5">
            <p
              data-reveal="rise"
              className="mb-6 max-w-[38ch] leading-snug text-[var(--ink-soft)]"
              style={{ fontSize: 'var(--text-base)' }}
            >
              Рекламодатель публикует предложение. FlipHouse подбирает клипы, где
              оно уместно, и встраивает его как
              {' '}
              <b className="font-bold text-[var(--foreground)]">нативный баннер</b>.
              Размер, момент и место подобраны так, что баннер читается частью
              ролика.
              {' '}
              <b className="font-bold text-[var(--foreground)]">Автор получает деньги за показы и конверсии.</b>
              {' '}
              Без личных переписок, рекламных презентаций и торга за фикс.
            </p>

            <div data-reveal-group="rise" className="grid grid-cols-1 sm:grid-cols-2">
              <div data-reveal-item className="border-b border-[var(--rule)] py-4 pr-4 sm:border-r">
                <h4 className="mb-1 font-mono text-[0.72rem] uppercase tracking-[0.14em] text-[var(--pop)]">
                  Авторам
                </h4>
                <p className="font-[family-name:var(--font-narrow)] leading-snug text-[var(--ink-soft)]">
                  Превратите старые клипы в источник дохода. Принимайте
                  предложения, которые нравятся, держите редакторский контроль,
                  получайте деньги за результат.
                </p>
              </div>
              <div data-reveal-item className="border-b border-[var(--rule)] py-4 sm:pl-4">
                <h4 className="mb-1 font-mono text-[0.72rem] uppercase tracking-[0.14em] text-[var(--cobalt)]">
                  Для рекламодателей
                </h4>
                <p className="font-[family-name:var(--font-narrow)] leading-snug text-[var(--ink-soft)]">
                  Покупайте размещения внутри ранжированных тематических роликов.
                  Платите за реальные показы и конверсии, по понятной ставке.
                </p>
              </div>
            </div>
          </div>

          <figure
            data-reveal="rise"
            className="col-span-12 border-[1.5px] border-[var(--rule-strong)] bg-[var(--muted)] p-6 text-[var(--foreground)] lg:col-span-6 lg:col-start-7"
            aria-label="Клип креатора с нативным баннером рекламодателя и выплатой"
          >
            <div className="mb-6 flex items-baseline justify-between border-b border-[color-mix(in_oklch,var(--foreground)_22%,transparent)] pb-4">
              <span className="font-mono text-[0.72rem] uppercase tracking-[0.14em] text-[color-mix(in_oklch,var(--foreground)_70%,transparent)]">
                Клип #01 · нативное размещение
              </span>
              <span className="inline-flex items-center gap-1.5 font-mono text-[0.72rem] tracking-wide text-[var(--pop)]">
                <span aria-hidden className="size-1.5 rounded-full bg-[var(--pop)]" />
                ИДЁТ ОТКРУТКА
              </span>
            </div>

            <div className="grid grid-cols-[6rem_1fr] items-start gap-5 md:grid-cols-[7.2rem_1fr]">
              <div
                aria-hidden
                className="flex aspect-[9/16] flex-col justify-between border border-[color-mix(in_oklch,var(--foreground)_30%,transparent)] p-2"
              >
                <span className="font-mono text-[0.6rem] tracking-widest text-[color-mix(in_oklch,var(--foreground)_60%,transparent)]">
                  9 : 16
                </span>
                <div className="text-center font-[family-name:var(--font-grotesk)] text-[0.74rem] font-extrabold uppercase leading-[1.1] tracking-tight [overflow-wrap:anywhere]">
                  НИКТО НЕ
                  {' '}
                  <span className="text-[var(--pop)]">ПРИДЁТ</span>
                  {' '}
                  СПАСАТЬ ТВОЙ ЗАПУСК
                </div>
                <div className="rounded-sm border-[1.5px] border-[var(--pop)] bg-[color-mix(in_srgb,var(--pop)_30%,var(--background))] p-1 text-center font-mono text-[0.58rem] leading-tight tracking-wide">
                  SHIPFAST · ДЕПЛОЙ В 1 КЛИК
                  <br />
                  FLIP20 → −20%
                </div>
              </div>

              <div className="flex min-w-0 flex-col gap-2">
                {LEDGER.map(row => (
                  <div
                    key={row.label}
                    className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 border-b border-[color-mix(in_oklch,var(--foreground)_16%,transparent)] pb-2 font-mono text-sm"
                  >
                    <span className="tracking-wide text-[color-mix(in_oklch,var(--foreground)_70%,transparent)]">
                      {row.label}
                    </span>
                    <span
                      className={`tabular-nums font-semibold ${row.payout ? 'text-base text-[var(--pop)]' : ''}`}
                    >
                      {row.value}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <figcaption className="mt-6 border-t border-[color-mix(in_oklch,var(--foreground)_22%,transparent)] pt-4 font-[family-name:var(--font-narrow)] text-sm text-[color-mix(in_oklch,var(--foreground)_78%,transparent)]">
              Баннер живёт внутри клипа. Никаких пре-роллов и прерываний.
              Читаемый, в стиле бренда, с оплатой за результат для автора.
            </figcaption>
          </figure>
        </div>
      </div>
    </section>
  );
}
