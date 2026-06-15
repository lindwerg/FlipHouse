import { describe, expect, it } from 'vitest';
import { getPaymentProvider, selectProvider } from './PaymentProvider';
import { mockPaymentProvider } from './provider/mock';
import { tronPaymentProvider } from './provider/tron';

// The deposit address is the on-chain surface of PaymentProvider. In P1.12 the
// real TRON HD-derive + tronweb land at checkpoint F; the mock derives a
// deterministic per-user TRC-20-shaped address so the deposit UI + unit tests
// run without any network or key material.
describe('deposit address (PaymentProvider)', () => {
  it('getDepositAddress derives a deterministic per-user TRC-20 address (HD path)', async () => {
    const first = await mockPaymentProvider.getDepositAddress('user_1');
    const again = await mockPaymentProvider.getDepositAddress('user_1');
    const other = await mockPaymentProvider.getDepositAddress('user_2');

    // Same user → same address (deterministic derivation).
    expect(first).toBe(again);
    // Different user → different address.
    expect(first).not.toBe(other);
    // TRC-20 shape: base58, starts with 'T', 34 chars.
    expect(first).toMatch(/^T[1-9A-HJ-NP-Za-km-z]{33}$/);
  });

  it('selects the mock provider by default and tron when configured', () => {
    expect(selectProvider('mock')).toBe(mockPaymentProvider);
    expect(selectProvider('tron')).toBe(tronPaymentProvider);
    // The env-driven factory resolves to a real provider object.
    expect(typeof getPaymentProvider().getDepositAddress).toBe('function');
  });

  it('mock createPayout returns a deterministic txid', async () => {
    const first = await mockPaymentProvider.createPayout('Taddr', 1);
    const again = await mockPaymentProvider.createPayout('Taddr', 1);
    const other = await mockPaymentProvider.createPayout('Taddr', 2);

    expect(first).toBe(again);
    expect(first).not.toBe(other);
    expect(first).toMatch(/^[0-9a-f]{64}$/);
  });

  it('tron provider throws until it lands at checkpoint F', async () => {
    await expect(tronPaymentProvider.getDepositAddress('user_1')).rejects.toThrow(
      /checkpoint F/,
    );
    await expect(
      tronPaymentProvider.createPayout('Taddr', 1),
    ).rejects.toThrow(/checkpoint F/);
  });
});
