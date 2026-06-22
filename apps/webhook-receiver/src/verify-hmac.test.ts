import { createHmac } from 'node:crypto';

import { expect, test } from 'vitest';

import {
  extractHexDigest,
  isWithinReplayWindow,
  parseTimestamp,
  REPLAY_WINDOW_SEC,
  verifyHmac,
} from './verify-hmac.js';

const SECRET = 'whsec_test';
const BODY = '{"request_id":"u","status":"succeeded"}';
const NOW = 1_700_000_000;

function signature(secret: string, timestamp: number, body: string): string {
  const digest = createHmac('sha256', secret)
    .update(`${timestamp}.${body}`)
    .digest('hex');
  return `sha256=${digest}`;
}

// extractHexDigest

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

// parseTimestamp

test('parseTimestamp parses a numeric header', () => {
  expect(parseTimestamp('1700000000')).toBe(1_700_000_000);
});

test('parseTimestamp returns undefined for an empty header', () => {
  expect(parseTimestamp('')).toBeUndefined();
});

test('parseTimestamp returns undefined for a non-numeric header', () => {
  expect(parseTimestamp('12x')).toBeUndefined();
});

// isWithinReplayWindow

test('isWithinReplayWindow accepts a timestamp at the edge of the window', () => {
  expect(isWithinReplayWindow(NOW - REPLAY_WINDOW_SEC, NOW)).toBe(true);
  expect(isWithinReplayWindow(NOW + REPLAY_WINDOW_SEC, NOW)).toBe(true);
});

test('isWithinReplayWindow rejects a timestamp just outside the window', () => {
  expect(isWithinReplayWindow(NOW - REPLAY_WINDOW_SEC - 1, NOW)).toBe(false);
  expect(isWithinReplayWindow(NOW + REPLAY_WINDOW_SEC + 1, NOW)).toBe(false);
});

// verifyHmac

test('valid signature within the window returns true', () => {
  expect(
    verifyHmac({
      secret: SECRET,
      rawBody: BODY,
      signatureHeader: signature(SECRET, NOW, BODY),
      timestampHeader: String(NOW),
      nowSec: NOW,
    }),
  ).toBe(true);
});

test('wrong secret returns false', () => {
  expect(
    verifyHmac({
      secret: 'whsec_wrong',
      rawBody: BODY,
      signatureHeader: signature(SECRET, NOW, BODY),
      timestampHeader: String(NOW),
      nowSec: NOW,
    }),
  ).toBe(false);
});

test('tampered body returns false', () => {
  expect(
    verifyHmac({
      secret: SECRET,
      rawBody: `${BODY} tampered`,
      signatureHeader: signature(SECRET, NOW, BODY),
      timestampHeader: String(NOW),
      nowSec: NOW,
    }),
  ).toBe(false);
});

test('a signature computed without the timestamp prefix returns false', () => {
  const bareDigest = createHmac('sha256', SECRET).update(BODY).digest('hex');
  expect(
    verifyHmac({
      secret: SECRET,
      rawBody: BODY,
      signatureHeader: `sha256=${bareDigest}`,
      timestampHeader: String(NOW),
      nowSec: NOW,
    }),
  ).toBe(false);
});

test('a stale timestamp outside the replay window returns false', () => {
  const stale = NOW - REPLAY_WINDOW_SEC - 1;
  expect(
    verifyHmac({
      secret: SECRET,
      rawBody: BODY,
      signatureHeader: signature(SECRET, stale, BODY),
      timestampHeader: String(stale),
      nowSec: NOW,
    }),
  ).toBe(false);
});

test('a missing/invalid timestamp header returns false', () => {
  expect(
    verifyHmac({
      secret: SECRET,
      rawBody: BODY,
      signatureHeader: signature(SECRET, NOW, BODY),
      timestampHeader: '',
      nowSec: NOW,
    }),
  ).toBe(false);
});

test('missing sha256= prefix returns false', () => {
  const digest = createHmac('sha256', SECRET).update(`${NOW}.${BODY}`).digest('hex');
  expect(
    verifyHmac({
      secret: SECRET,
      rawBody: BODY,
      signatureHeader: digest,
      timestampHeader: String(NOW),
      nowSec: NOW,
    }),
  ).toBe(false);
});

test('empty signature header returns false', () => {
  expect(
    verifyHmac({
      secret: SECRET,
      rawBody: BODY,
      signatureHeader: '',
      timestampHeader: String(NOW),
      nowSec: NOW,
    }),
  ).toBe(false);
});

test('short/truncated digest returns false (length guard, no throw)', () => {
  expect(
    verifyHmac({
      secret: SECRET,
      rawBody: BODY,
      signatureHeader: 'sha256=abcd',
      timestampHeader: String(NOW),
      nowSec: NOW,
    }),
  ).toBe(false);
});

test('defaults nowSec to the wall clock when omitted (current timestamp passes)', () => {
  const now = Math.floor(Date.now() / 1000);
  expect(
    verifyHmac({
      secret: SECRET,
      rawBody: BODY,
      signatureHeader: signature(SECRET, now, BODY),
      timestampHeader: String(now),
    }),
  ).toBe(true);
});
