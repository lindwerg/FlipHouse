import type { Metadata } from 'next';
import { setRequestLocale } from 'next-intl/server';
import { AccountTypeChoice } from './AccountTypeChoice';

type OnboardingProps = {
  params: Promise<{ locale: string }>;
};

export function generateMetadata(): Metadata {
  return {
    title: 'Тип аккаунта — FlipHouse',
    description: 'Выберите, как вы используете FlipHouse: креатор или рекламодатель.',
  };
}

export default async function OnboardingPage(props: OnboardingProps) {
  const { locale } = await props.params;
  setRequestLocale(locale);

  return (
    <main className="min-h-screen bg-[var(--background)] py-[clamp(4rem,3rem+5vw,7rem)] text-[var(--foreground)]">
      <div className="mx-auto w-full max-w-[1100px] px-[var(--space-margin)]">
        <p className="font-mono text-sm font-semibold tracking-wide text-[var(--pop)]">
          Последний шаг · Тип аккаунта
        </p>
        <h1
          className="mt-3 max-w-[18ch] font-[family-name:var(--font-grotesk)] font-black leading-[0.95] tracking-[-0.03em]"
          style={{ fontSize: 'clamp(2.4rem, 1rem + 6vw, 5.5rem)' }}
        >
          Кто вы на FlipHouse?
        </h1>
        <p className="mt-4 mb-10 max-w-[52ch] font-[family-name:var(--font-narrow)] leading-snug text-[var(--ink-soft)] md:mb-14">
          Выбор задаёт ваш дашборд и права. Его можно сделать только один раз —
          креаторы загружают видео и зарабатывают, рекламодатели размещают
          офферы.
        </p>

        <AccountTypeChoice locale={locale} />
      </div>
    </main>
  );
}
