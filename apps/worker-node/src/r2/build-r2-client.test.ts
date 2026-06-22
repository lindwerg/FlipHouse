import { expect, test } from 'vitest';

import { resolveR2Env } from './build-r2-client.js';

const FULL_ENV = {
  R2_ACCOUNT_ID: 'acct',
  R2_BUCKET: 'bucket',
  R2_ACCESS_KEY_ID: 'AK',
  R2_SECRET_ACCESS_KEY: 'SK',
};

/** No accountId AND no endpoint override — must fail naming R2_ACCOUNT_ID. */
const FULL_ENV_WITHOUT_ACCOUNT = {
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

test('resolveR2Env uses R2_ENDPOINT override and does not require R2_ACCOUNT_ID', () => {
  const env = {
    R2_ENDPOINT: 'https://t3.storageapi.dev',
    R2_BUCKET: 'bucket',
    R2_ACCESS_KEY_ID: 'AK',
    R2_SECRET_ACCESS_KEY: 'SK',
  };
  expect(resolveR2Env(env)).toEqual({
    endpoint: 'https://t3.storageapi.dev',
    bucket: 'bucket',
    accessKeyId: 'AK',
    secretAccessKey: 'SK',
  });
});

test('resolveR2Env still requires R2_BUCKET / keys even with an endpoint override', () => {
  const base = {
    R2_ENDPOINT: 'https://t3.storageapi.dev',
    R2_BUCKET: 'bucket',
    R2_ACCESS_KEY_ID: 'AK',
    R2_SECRET_ACCESS_KEY: 'SK',
  };
  for (const key of ['R2_BUCKET', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY']) {
    expect(() => resolveR2Env({ ...base, [key]: undefined })).toThrow(new RegExp(key));
  }
});

test('resolveR2Env falls back to requiring R2_ACCOUNT_ID when R2_ENDPOINT is unset', () => {
  expect(() => resolveR2Env(FULL_ENV_WITHOUT_ACCOUNT)).toThrow(/R2_ACCOUNT_ID/);
});

test('resolveR2Env treats an empty-string R2_ENDPOINT as unset (falls back to accountId)', () => {
  const env = { ...FULL_ENV, R2_ENDPOINT: '' };
  expect(resolveR2Env(env)).toEqual({
    accountId: 'acct',
    bucket: 'bucket',
    accessKeyId: 'AK',
    secretAccessKey: 'SK',
  });
});
