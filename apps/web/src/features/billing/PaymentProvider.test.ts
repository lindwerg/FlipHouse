import { describe, expect, it } from 'vitest';
import {
  MockProviderInProductionError,
  selectProvider,
} from './PaymentProvider';

// Prod-safety guard (P2 step #8). The mock provider derives fake deposit
// addresses + fake txids with no chain behind them; running it in production
// would silently "bill" against a stub. selectProvider must fail the deploy at
// construction time when NODE_ENV=production resolves the mock — loud, not
// silent. nodeEnv is injected so the guard is deterministic (no env mutation).
describe('PaymentProvider prod-mock guard', () => {
  it('throws MockProviderInProductionError for mock + production', () => {
    expect(() => selectProvider('mock', 'production')).toThrow(
      MockProviderInProductionError,
    );
  });

  it('returns the tron provider for tron + production (real billing is allowed)', () => {
    const provider = selectProvider('tron', 'production');
    expect(provider.getDepositAddress).toBeTypeOf('function');
    expect(provider.createPayout).toBeTypeOf('function');
  });

  it('returns the mock provider for mock + non-production (dev/test/undefined)', () => {
    for (const nodeEnv of ['development', 'test', undefined]) {
      const provider = selectProvider('mock', nodeEnv);
      expect(provider.getDepositAddress).toBeTypeOf('function');
      expect(provider.createPayout).toBeTypeOf('function');
    }
  });
});
