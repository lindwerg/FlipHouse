import { auth } from '@clerk/nextjs/server';
import { setRequestLocale } from 'next-intl/server';
import { DepositPanel } from '@/features/billing/DepositPanel';
import { getPaymentProvider } from '@/features/billing/PaymentProvider';
import { requireAccountType } from '@/libs/rbac';

type CreatorDashboardProps = {
  params: Promise<{ locale: string }>;
};

export default async function CreatorDashboardPage(props: CreatorDashboardProps) {
  const { locale } = await props.params;
  setRequestLocale(locale);
  await requireAccountType('creator', locale);

  const { userId } = await auth();
  const depositAddress = userId
    ? await getPaymentProvider().getDepositAddress(userId)
    : null;

  return (
    <section aria-labelledby="creator-dashboard-heading">
      <p className="font-mono text-sm font-semibold tracking-wide text-[var(--pop)]">
        Дашборд · Креатор
      </p>
      <h1
        id="creator-dashboard-heading"
        data-account-type="creator"
        className="mt-2 font-[family-name:var(--font-grotesk)] font-extrabold leading-[0.98] tracking-tight"
        style={{ fontSize: 'clamp(2rem, 1.2rem + 3vw, 3.4rem)' }}
      >
        Кабинет креатора
      </h1>
      <p className="mt-3 max-w-[52ch] font-[family-name:var(--font-narrow)] leading-snug text-[var(--ink-soft)]">
        Загружайте видео и получайте ранжированные вертикальные клипы. Загрузка и
        очередь нарезки появятся в следующих шагах.
      </p>

      {depositAddress ? <DepositPanel address={depositAddress} /> : null}
    </section>
  );
}
