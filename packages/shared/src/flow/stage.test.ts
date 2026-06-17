import { expect, test } from 'vitest';

import { QUEUE_NAMES, STAGES, isStage } from './stage.js';

test('STAGES lists the eight DAG nodes in children-run-first order', () => {
  expect(STAGES).toEqual([
    'transcode',
    'asr',
    'score',
    'reframe',
    'caption',
    'banner',
    'store',
    'publish',
  ]);
});

test('QUEUE_NAMES lists the five BullMQ queues', () => {
  expect(QUEUE_NAMES).toEqual(['transcode', 'gpu-asr', 'gpu-score', 'cpu', 'publish']);
});

test('isStage accepts a known stage', () => {
  expect(isStage('reframe')).toBe(true);
});

test('isStage rejects an unknown stage', () => {
  expect(isStage('thumbnail')).toBe(false);
});
