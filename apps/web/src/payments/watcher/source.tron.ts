import type { TronChainSource } from './source';

// Real on-chain TRON source: polls our own node / TronGrid for USDT TRC-20
// Transfer events to our deposit addresses. The HTTP client, retries, rate limits
// and the TRONGRID_API_KEY land at CHECKPOINT F (P1.13), running against a TRON
// testnet (Nile/Shasta). Until then it fails loudly rather than silently — the
// fixture source backs all integration tests.

const NOT_READY = 'TRON chain source lands at checkpoint F (P1.13)';

export const tronChainSource: TronChainSource = {
  getCurrentBlock(): Promise<number> {
    return Promise.reject(new Error(NOT_READY));
  },
  getTransferEvents(): Promise<never> {
    return Promise.reject(new Error(NOT_READY));
  },
};
