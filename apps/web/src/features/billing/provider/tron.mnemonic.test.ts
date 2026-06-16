import { describe, expect, it, vi } from 'vitest';

// Isolated file: mock Env so TRON_HD_MNEMONIC is absent. The tron provider must
// fail fast (and never echo the missing secret) rather than derive from nothing.
// Kept separate from tron.test.ts, whose vectors need the real test mnemonic.
vi.mock('@/libs/Env', () => ({
  Env: { TRON_HD_MNEMONIC: undefined },
}));

describe('tron payment provider without a configured mnemonic', () => {
  it('rejects getDepositAddress when TRON_HD_MNEMONIC is missing', async () => {
    const { tronPaymentProvider } = await import('./tron');
    await expect(
      tronPaymentProvider.getDepositAddress('user_1', 0),
    ).rejects.toThrow(/TRON_HD_MNEMONIC is not configured/);
  });
});
