'use client';

import type { AccountType } from '@/libs/accountType';
import { useTransition } from 'react';
import { selectAccountType } from './actions';

type Choice = {
  type: AccountType;
  num: string;
  title: string;
  blurb: string;
};

// Swiss Pop onboarding split (docs/design-reference/swiss-pop.html language):
// two editorial cards — pick who you are on FlipHouse. Russian product copy,
// brand stays latin. The chosen type is written immutably server-side and the
// action redirects to the matching dashboard.
const CHOICES: Choice[] = [
  {
    type: 'creator',
    num: '01',
    title: 'Креатор',
    blurb:
      'Загружаю длинные видео, получаю ранжированные вертикальные клипы 9:16 с субтитрами и зарабатываю на встроенной рекламе.',
  },
  {
    type: 'advertiser',
    num: '02',
    title: 'Рекламодатель',
    blurb:
      'Размещаю офферы — баннеры встраиваются в клипы креаторов. Плачу за показы и конверсии, контролирую бренд-безопасность.',
  },
];

type AccountTypeChoiceProps = {
  locale: string;
};

export function AccountTypeChoice({ locale }: AccountTypeChoiceProps) {
  const [isPending, startTransition] = useTransition();

  const choose = (type: AccountType) => {
    startTransition(async () => {
      await selectAccountType(type, locale);
    });
  };

  return (
    <div className="grid grid-cols-1 gap-[var(--space-gutter)] md:grid-cols-2">
      {CHOICES.map(choice => (
        <button
          key={choice.type}
          type="button"
          data-account-type={choice.type}
          disabled={isPending}
          onClick={() => choose(choice.type)}
          className="group flex flex-col items-start gap-4 border-[1.5px] border-[var(--rule-strong)] bg-[var(--background)] p-8 text-left transition-colors duration-300 hover:border-[var(--pop)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--pop)] disabled:cursor-not-allowed disabled:opacity-60 md:p-10"
        >
          <span className="font-mono text-lg font-semibold tracking-wide text-[var(--pop)]">
            {choice.num}
          </span>
          <span
            className="font-[family-name:var(--font-grotesk)] font-extrabold leading-[0.98] tracking-tight text-[var(--foreground)]"
            style={{ fontSize: 'clamp(2rem, 1.2rem + 3vw, 3.4rem)' }}
          >
            {choice.title}
          </span>
          <span className="max-w-[40ch] font-[family-name:var(--font-narrow)] leading-snug text-[var(--ink-soft)]">
            {choice.blurb}
          </span>
          <span
            aria-hidden
            className="mt-2 inline-flex items-center gap-2 font-mono text-sm font-semibold text-[var(--foreground)] transition-transform duration-300 group-hover:translate-x-1"
          >
            Выбрать
            <span>→</span>
          </span>
        </button>
      ))}
    </div>
  );
}
