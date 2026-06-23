import { auth } from '@clerk/nextjs/server';
import { setRequestLocale } from 'next-intl/server';
import { getSubscriptionSummary } from '@/features/billing/balance';
import { BalancePanel } from '@/features/billing/BalancePanel';
import { DepositPanel } from '@/features/billing/DepositPanel';
import { getPaymentProvider } from '@/features/billing/PaymentProvider';
import { MyClips } from '@/features/results/MyClips';
import { CreatorUploadPanel } from '@/features/upload/CreatorUploadPanel';
import { db } from '@/libs/DB';
import { requireAccountType } from '@/libs/rbac';
import { getOrCreateDepositAddress } from '@/payments/watcher/depositAddress';

type CreatorDashboardProps = {
  params: Promise<{ locale: string }>;
};

export default async function CreatorDashboardPage(props: CreatorDashboardProps) {
  const { locale } = await props.params;
  setRequestLocale(locale);
  await requireAccountType('creator', locale);

  const { userId } = await auth();
  // Derive + persist the per-user TRC-20 deposit address so the on-chain watcher
  // can reverse-map an incoming transfer back to this user (P1.13).
  const depositAddress = userId
    ? await getOrCreateDepositAddress(db, getPaymentProvider(), userId)
    : null;
  // Prepaid balance + plan for display (P1.16). Defaults to free/0 with no row.
  const billing = userId
    ? await getSubscriptionSummary(db, userId)
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
        Загружайте видео и получайте ранжированные вертикальные клипы. Очередь
        нарезки появится в следующих шагах.
      </p>

      <CreatorUploadPanel />

      <MyClips />

      {billing
        ? (
            <BalancePanel
              balanceUsdt={billing.balanceUsdt}
              plan={billing.plan}
              subscriptionStatus={billing.subscriptionStatus}
            />
          )
        : null}
      {depositAddress ? <DepositPanel address={depositAddress} /> : null}
    </section>
  );
}
