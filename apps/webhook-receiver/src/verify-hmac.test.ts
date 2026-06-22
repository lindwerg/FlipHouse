import { createHmac } from 'node:crypto';

import { expect, test } from 'vitest';

import { extractHexDigest, verifyHmac } from './verify-hmac.js';

const SECRET = 'whsec_test';
const BODY = '{"id":"pred_1","status":"succeeded"}';

function signature(secret: string, body: string): string {
  const digest = createHmac('sha256', secret).update(body).digest('hex');
  return `sha256=${digest}`;
}

test('extractHexDigest pulls the hex out of a sha256= header', () => {
  expect(extractHexDigest('sha256=abcdef0123')).toBe('abcdef0123');
});

test('extractHexDigest returns undefined without the sha256= prefix', () => {
  expect(extractHexDigest('md5=abcdef')).toBeUndefined();
});

test('extractHexDigest returns undefined for an empty header', () => {
  expect(extractHexDigest('')).toBeUndefined();
});

test('extractHexDigest returns undefined for a non-hex digest', () => {
  expect(extractHexDigest('sha256=not-hex-zz')).toBeUndefined();
});

test('valid HMAC returns true', () => {
  expect(verifyHmac(SECRET, BODY, signature(SECRET, BODY))).toBe(true);
});

test('wrong secret returns false', () => {
  expect(verifyHmac('whsec_wrong', BODY, signature(SECRET, BODY))).toBe(false);
});

test('tampered body returns false', () => {
  const sig = signature(SECRET, BODY);
  expect(verifyHmac(SECRET, `${BODY} tampered`, sig)).toBe(false);
});

test('missing sha256= prefix returns false', () => {
  const digest = createHmac('sha256', SECRET).update(BODY).digest('hex');
  expect(verifyHmac(SECRET, BODY, digest)).toBe(false);
});

test('empty header returns false', () => {
  expect(verifyHmac(SECRET, BODY, '')).toBe(false);
});

test('short/truncated digest returns false (length guard, no throw)', () => {
  expect(verifyHmac(SECRET, BODY, 'sha256=abcd')).toBe(false);
});
