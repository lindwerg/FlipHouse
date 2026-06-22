import { Env } from '@/libs/Env';
import { mockPaymentProvider } from './provider/mock';
import { tronPaymentProvider } from './provider/tron';

// Vendor-neutral on-chain billing surface (same pattern as PublishProvider in P6).
// The concrete impl is our own TRON USDT TRC-20 receiver — no third-party PSP, so
// nobody can freeze funds at the processor layer. Off-chain ledger ops (balance
// credit/debit) live in balance.ts; only the chain-specific parts are here.

export type PaymentProviderKind = 'tron' | 'mock';

/**
 * Thrown when a production deploy resolves the `mock` PaymentProvider. The mock
 * derives fake deposit addresses and fake txids with no chain behind them, so
 * letting it run in production would silently "bill" users against a stub. This
 * fails the deploy at provider construction instead — loud, not silent.
 */
export class MockProviderInProductionError extends Error {
  constructor() {
    super(
      'PAYMENT_PROVIDER=mock resolved while NODE_ENV=production — refusing to run ' +
        'stub crypto billing in production. Set PAYMENT_PROVIDER=tron (and provision ' +
        'the on-chain credentials) before deploying.',
    );
    this.name = 'MockProviderInProductionError';
  }
}

export type PaymentProvider = {
  /**
   * Derives a per-user TRC-20 deposit address at the given HD index. The provider
   * is a pure deriver: the sequential index is allocated by the DB-aware
   * orchestrator (payments/watcher/depositAddress.ts) so the wallet stays
   * recoverable by scanning m/44'/195'/0'/0/0..N. The mock ignores the index.
   */
  getDepositAddress: (userId: string, index: number) => Promise<string>;
  /** Signs + broadcasts a USDT TRC-20 transfer; returns the txid. */
  createPayout: (toAddress: string, amountUsdt: number) => Promise<string>;
};

/**
 * Select the concrete provider for `kind`. In production the `mock` provider is
 * a deploy-failing mistake (fake billing), so it throws
 * {@link MockProviderInProductionError} rather than constructing the stub. The
 * `nodeEnv` is injected (defaulting to {@link Env.NODE_ENV}) so the guard is
 * deterministically unit-testable.
 */
export function selectProvider(
  kind: PaymentProviderKind,
  nodeEnv: string | undefined = Env.NODE_ENV,
): PaymentProvider {
  if (kind === 'mock' && nodeEnv === 'production') {
    throw new MockProviderInProductionError();
  }
  return kind === 'tron' ? tronPaymentProvider : mockPaymentProvider;
}

/** Resolves the configured PaymentProvider from env (PAYMENT_PROVIDER). */
export function getPaymentProvider(): PaymentProvider {
  return selectProvider(Env.PAYMENT_PROVIDER);
}
