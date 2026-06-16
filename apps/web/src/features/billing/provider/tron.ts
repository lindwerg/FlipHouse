import { TronWeb } from 'tronweb';
import { Env } from '@/libs/Env';
import type { PaymentProvider } from '../PaymentProvider';

// Real on-chain TRON USDT TRC-20 provider (P1.13.1). getDepositAddress is a pure
// HD deriver: (master mnemonic, BIP44 index) → TRC-20 address, no DB and no
// network. The sequential per-user index is allocated by the DB-aware
// orchestrator (payments/watcher/depositAddress.ts). The master mnemonic is a
// SECRET read from env (.env.local / KMS) — never hardcoded, never logged.
//
// createPayout (signing + broadcasting) needs the hot private key and lands in
// P5; until then it fails loudly rather than silently.

// SLIP-44 coin type 195 = TRON. Account 0, external chain, per-user address index.
const TRON_BIP44_PREFIX = "m/44'/195'/0'/0/";

const PAYOUT_NOT_READY =
  'TRON payouts land in P5 (signing needs the KMS hot key); checkpoint F covers the deposit path only';

function depositPath(index: number): string {
  return `${TRON_BIP44_PREFIX}${index}`;
}

export const tronPaymentProvider: PaymentProvider = {
  getDepositAddress(_userId: string, index: number): Promise<string> {
    const mnemonic = Env.TRON_HD_MNEMONIC;
    if (!mnemonic) {
      // Fail fast with the variable name, never echo the (absent) secret.
      return Promise.reject(
        new Error('TRON_HD_MNEMONIC is not configured (.env.local / KMS)'),
      );
    }
    // fromMnemonic is static and offline: it only does BIP39/BIP44 key math.
    const account = TronWeb.fromMnemonic(mnemonic, depositPath(index));
    return Promise.resolve(account.address);
  },
  createPayout(): Promise<string> {
    return Promise.reject(new Error(PAYOUT_NOT_READY));
  },
};
