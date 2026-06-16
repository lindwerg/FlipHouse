import type { PlanId } from './plans';
import type { SubscriptionStatus } from './balance';

// Swiss-styled balance + plan readout for the creator dashboard. Presentational
// only — the server page reads the values and passes them in. Covered by the
// signup→fund→dashboard e2e (P1.16).

type BalancePanelProps = {
  balanceUsdt: number;
  plan: PlanId;
  subscriptionStatus: SubscriptionStatus | null;
};

const PLAN_LABELS: Record<PlanId, string> = {
  free: 'Бесплатно',
  start: 'Старт',
  active: 'Актив',
  studio: 'Студия',
  payg: 'PAYG',
};

const STATUS_LABELS: Record<SubscriptionStatus, string> = {
  active: 'активна',
  past_due: 'просрочена',
  canceled: 'отменена',
};

/** Formats a USDT amount with two decimals, e.g. 50 → "50.00". */
function formatUsdt(amount: number): string {
  return amount.toFixed(2);
}

export function BalancePanel({
  balanceUsdt,
  plan,
  subscriptionStatus,
}: BalancePanelProps) {
  return (
    <section
      aria-labelledby="balance-heading"
      className="mt-10 border-[1.5px] border-[var(--rule-strong)] p-6 md:p-8"
    >
      <p className="font-mono text-sm font-semibold tracking-wide text-[var(--pop)]">
        Баланс · USDT
      </p>
      <h2
        id="balance-heading"
        data-slot="balance"
        className="mt-2 font-[family-name:var(--font-grotesk)] text-4xl font-extrabold tracking-tight tabular-nums"
      >
        {formatUsdt(balanceUsdt)}
        {' '}
        <span className="text-2xl text-[var(--ink-soft)]">USDT</span>
      </h2>

      <p className="mt-3 font-[family-name:var(--font-narrow)] leading-snug text-[var(--ink-soft)]">
        Тариф:
        {' '}
        <span data-slot="plan" className="font-semibold text-[var(--ink)]">
          {PLAN_LABELS[plan]}
        </span>
        {subscriptionStatus
          ? ` · подписка ${STATUS_LABELS[subscriptionStatus]}`
          : null}
      </p>
    </section>
  );
}
