import { setRequestLocale } from 'next-intl/server';
import { requireAccountType } from '@/libs/rbac';

type AdvertiserDashboardProps = {
  params: Promise<{ locale: string }>;
};

export default async function AdvertiserDashboardPage(props: AdvertiserDashboardProps) {
  const { locale } = await props.params;
  setRequestLocale(locale);
  await requireAccountType('advertiser', locale);

  return (
    <section aria-labelledby="advertiser-dashboard-heading">
      <p className="font-mono text-sm font-semibold tracking-wide text-[var(--cobalt)]">
        Дашборд · Рекламодатель
      </p>
      <h1
        id="advertiser-dashboard-heading"
        data-account-type="advertiser"
        className="mt-2 font-[family-name:var(--font-grotesk)] font-extrabold leading-[0.98] tracking-tight"
        style={{ fontSize: 'clamp(2rem, 1.2rem + 3vw, 3.4rem)' }}
      >
        Кабинет рекламодателя
      </h1>
      <p className="mt-3 max-w-[52ch] font-[family-name:var(--font-narrow)] leading-snug text-[var(--ink-soft)]">
        Размещайте офферы и следите за показами в клипах креаторов. Конструктор
        офферов и бренд-безопасность появятся в следующих шагах.
      </p>
    </section>
  );
}
