import { UnrecoverableError } from 'bullmq';
import { expect, test } from 'vitest';

import { stageErrorFrom, toBullError } from './classify.js';

test('toBullError maps a fatal kind to a non-retryable UnrecoverableError', () => {
  const err = toBullError('fatal', 'OPENROUTER_402', 'credits exhausted');

  expect(err).toBeInstanceOf(UnrecoverableError);
  expect(err.message).toBe('OPENROUTER_402: credits exhausted');
});

test('toBullError maps a retryable kind to a plain Error (BullMQ will retry)', () => {
  const err = toBullError('retryable', 'CONN', 'timeout');

  expect(err).toBeInstanceOf(Error);
  expect(err).not.toBeInstanceOf(UnrecoverableError);
  expect(err.message).toBe('CONN: timeout');
});

test('stageErrorFrom preserves the failure kind from a stage result', () => {
  const fatal = stageErrorFrom({ ok: false, kind: 'fatal', code: 'BAD_INPUT', message: 'x' });
  const retryable = stageErrorFrom({ ok: false, kind: 'retryable', code: '5XX', message: 'y' });

  expect(fatal).toBeInstanceOf(UnrecoverableError);
  expect(retryable).not.toBeInstanceOf(UnrecoverableError);
});
