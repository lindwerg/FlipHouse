import { Env } from '@/libs/Env';
import { mockPaymentProvider } from './provider/mock';
import { tronPaymentProvider } from './provider/tron';

// Vendor-neutral on-chain billing surface (same pattern as PublishProvider in P6).
// The concrete impl is our own TRON USDT TRC-20 receiver — no third-party PSP, so
// nobody can freeze funds at the processor layer. Off-chain ledger ops (balance
// credit/debit) live in balance.ts; only the chain-specific parts are here.

export type PaymentProviderKind = 'tron' | 'mock';

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

export function selectProvider(kind: PaymentProviderKind): PaymentProvider {
  return kind === 'tron' ? tronPaymentProvider : mockPaymentProvider;
}

/** Resolves the configured PaymentProvider from env (PAYMENT_PROVIDER). */
export function getPaymentProvider(): PaymentProvider {
  return selectProvider(Env.PAYMENT_PROVIDER);
}
