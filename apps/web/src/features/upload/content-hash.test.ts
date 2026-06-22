import { describe, expect, it } from 'vitest';
import { isValidContentHash } from './content-hash';

describe('isValidContentHash', () => {
  it('accepts a 64-char lowercase hex digest', () => {
    expect(isValidContentHash('a'.repeat(64))).toBe(true);
    expect(isValidContentHash('0123456789abcdef'.repeat(4))).toBe(true);
  });

  it('rejects an uppercase digest', () => {
    expect(isValidContentHash('A'.repeat(64))).toBe(false);
  });

  it('rejects a digest of the wrong length', () => {
    expect(isValidContentHash('a'.repeat(63))).toBe(false);
    expect(isValidContentHash('a'.repeat(65))).toBe(false);
  });

  it('rejects a string with non-hex characters', () => {
    expect(isValidContentHash('g'.repeat(64))).toBe(false);
  });

  it('rejects an empty string', () => {
    expect(isValidContentHash('')).toBe(false);
  });
});
