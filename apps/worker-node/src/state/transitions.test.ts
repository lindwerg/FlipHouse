import { expect, test } from 'vitest';

import { validTransition } from './transitions.js';

test('allows a strictly forward step', () => {
  expect(validTransition('queued', 'hashing')).toBe(true);
  expect(validTransition('scoring', 'reframing')).toBe(true);
  expect(validTransition('publishing', 'done')).toBe(true);
});

test('rejects a backward or same-state step', () => {
  expect(validTransition('scoring', 'transcoding')).toBe(false);
  expect(validTransition('scoring', 'scoring')).toBe(false);
});

test('any in-flight status may move to failed', () => {
  expect(validTransition('queued', 'failed')).toBe(true);
  expect(validTransition('rendering', 'failed')).toBe(true);
});

test('duplicate is reachable only from queued (the claim-skip)', () => {
  expect(validTransition('queued', 'duplicate')).toBe(true);
  expect(validTransition('scoring', 'duplicate')).toBe(false);
});

test('terminal states never transition out', () => {
  expect(validTransition('done', 'failed')).toBe(false);
  expect(validTransition('failed', 'queued')).toBe(false);
  expect(validTransition('duplicate', 'hashing')).toBe(false);
});
