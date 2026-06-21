import { expect, test } from 'vitest';

import { resolveR2Env } from './build-r2-client.js';

const FULL_ENV = {
  R2_ACCOUNT_ID: 'acct',
  R2_BUCKET: 'bucket',
  R2_ACCESS_KEY_ID: 'AK',
  R2_SECRET_ACCESS_KEY: 'SK',
};

test('resolveR2Env returns the validated R2 settings when all vars are present', () => {
  expect(resolveR2Env(FULL_ENV)).toEqual({
    accountId: 'acct',
    bucket: 'bucket',
    accessKeyId: 'AK',
    secretAccessKey: 'SK',
  });
});

test('resolveR2Env throws naming the first missing var (fail-fast at startup)', () => {
  for (const key of Object.keys(FULL_ENV)) {
    const partial = { ...FULL_ENV, [key]: undefined };
    expect(() => resolveR2Env(partial)).toThrow(new RegExp(key));
  }
});

test('resolveR2Env treats an empty-string var as missing', () => {
  expect(() => resolveR2Env({ ...FULL_ENV, R2_BUCKET: '' })).toThrow(/R2_BUCKET/);
});
