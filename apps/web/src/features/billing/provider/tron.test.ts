import { describe, expect, it } from 'vitest';
import { tronPaymentProvider } from './tron';

// Real TRON HD-wallet derivation (P1.13.1). The provider is a pure deriver:
// (master mnemonic, BIP44 index) → TRC-20 address. No DB, no network. The
// sequential index is allocated by the DB-aware orchestrator (depositAddress.ts).
//
// Vector: the canonical BIP39 test mnemonic ("abandon … about") derived at
// m/44'/195'/0'/0/{index} (SLIP-44 coin type 195). These addresses are the
// widely published TRON vectors for that mnemonic — they pin the derivation so a
// silent change in the derivation path or library would turn this test red. The
// test mnemonic is injected via Env (TEST_ENV_DEFAULTS), never a real wallet.
const ADDRESS_AT = {
  0: 'TUEZSdKsoDHQMeZwihtdoBiN46zxhGWYdH',
  1: 'TSeJkUh4Qv67VNFwY8LaAxERygNdy6NQZK',
} as const;

describe('tron payment provider (real HD derivation)', () => {
  it('derives a real TRC-20 address from the master mnemonic at BIP44 path m/44/195/0/0/index', async () => {
    // The index — not the userId — drives derivation; the orchestrator owns the
    // address↔user mapping. Different indices → different, known addresses.
    expect(await tronPaymentProvider.getDepositAddress('user_a', 0)).toBe(
      ADDRESS_AT[0],
    );
    expect(await tronPaymentProvider.getDepositAddress('user_b', 1)).toBe(
      ADDRESS_AT[1],
    );
    // Same index → same address regardless of who asks (pure function of index).
    expect(await tronPaymentProvider.getDepositAddress('user_c', 0)).toBe(
      ADDRESS_AT[0],
    );
    // TRC-20 shape: base58, 'T'-prefixed, 34 chars.
    expect(ADDRESS_AT[0]).toMatch(/^T[1-9A-HJ-NP-Za-km-z]{33}$/);
  });

  it('defers payouts to P5 (createPayout still parked at checkpoint F)', async () => {
    // P1.13.1 scope is the deposit path only; signing/broadcasting payouts needs
    // the hot private key (KMS) and lands in P5.
    await expect(tronPaymentProvider.createPayout('Taddr', 1)).rejects.toThrow(
      /checkpoint F|P5/,
    );
  });
});
