import type { PaymentProvider } from '../PaymentProvider';

// Real on-chain TRON USDT TRC-20 provider. The HD-wallet deposit-address
// derivation, tronweb signing, and payout broadcast land at CHECKPOINT F (P1.13),
// where the seed + hot-key come from KMS and we run against a TRON testnet
// (Nile/Shasta). Until then every method fails loudly rather than silently — the
// mock provider backs all dev + unit-test flows.

const NOT_READY = 'TRON provider lands at checkpoint F (P1.13)';

export const tronPaymentProvider: PaymentProvider = {
  getDepositAddress(): Promise<string> {
    return Promise.reject(new Error(NOT_READY));
  },
  createPayout(): Promise<string> {
    return Promise.reject(new Error(NOT_READY));
  },
};
