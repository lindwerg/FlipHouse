import { createHash } from 'node:crypto';
import type { PaymentProvider } from '../PaymentProvider';

// Deterministic mock PaymentProvider for dev + unit tests. It derives a
// TRC-20-shaped address (base58, 'T'-prefixed, 34 chars) from a hash of the
// userId — no network, no key material. The real HD-wallet derivation + tronweb
// payouts land in provider/tron.ts at checkpoint F.

// Base58 alphabet (Bitcoin/TRON): no 0, O, I, l.
const BASE58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';

function deriveAddress(userId: string): string {
  const digest = createHash('sha256').update(userId).digest();
  let address = 'T';
  for (let i = 0; i < 33; i++) {
    address += BASE58[digest[i % digest.length]! % BASE58.length];
  }
  return address;
}

export const mockPaymentProvider: PaymentProvider = {
  getDepositAddress(userId: string): Promise<string> {
    return Promise.resolve(deriveAddress(userId));
  },
  createPayout(toAddress: string, amountUsdt: number): Promise<string> {
    // A deterministic fake txid so dev flows have something to echo.
    const txid = createHash('sha256')
      .update(`${toAddress}:${amountUsdt}`)
      .digest('hex');
    return Promise.resolve(txid);
  },
};
