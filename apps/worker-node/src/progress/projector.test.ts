import { STAGES } from '@fliphouse/shared';
import type { Stage } from '@fliphouse/shared';
import { expect, test } from 'vitest';

import {
  applyStageCompleted,
  buildFailureRecord,
  buildProgressUpdate,
  stageNameFromJobId,
  stageToStatus,
} from './projector.js';

const HASH = 'a'.repeat(64);

// --- stageNameFromJobId -------------------------------------------------

test('stageNameFromJobId maps a stage-prefixed jobId to its stage', () => {
  expect(stageNameFromJobId(`transcode-${HASH}`)).toBe('transcode');
  expect(stageNameFromJobId(`asr-${HASH}`)).toBe('asr');
});

test('stageNameFromJobId maps the flow- root jobId to the publish stage', () => {
  expect(stageNameFromJobId(`flow-${HASH}`)).toBe('publish');
});

test('stageNameFromJobId maps a publish-prefixed jobId directly to publish', () => {
  expect(stageNameFromJobId(`publish-${HASH}`)).toBe('publish');
});

test('stageNameFromJobId rejects an unknown prefix', () => {
  expect(stageNameFromJobId(`fanout-${HASH}`)).toBeUndefined();
  expect(stageNameFromJobId(`bad-${HASH}`)).toBeUndefined();
});

test('stageNameFromJobId rejects a malformed or missing content hash', () => {
  expect(stageNameFromJobId('transcode-')).toBeUndefined();
  expect(stageNameFromJobId(`transcode-${'a'.repeat(63)}`)).toBeUndefined();
  expect(stageNameFromJobId(`flow-${'a'.repeat(65)}`)).toBeUndefined();
});

test('stageNameFromJobId rejects an id with no dash and an empty string', () => {
  expect(stageNameFromJobId('nodash')).toBeUndefined();
  expect(stageNameFromJobId('')).toBeUndefined();
});

// --- stageToStatus ------------------------------------------------------

test('stageToStatus maps every stage to its ledger status', () => {
  expect(stageToStatus('transcode')).toBe('transcoding');
  expect(stageToStatus('asr')).toBe('transcribing');
  expect(stageToStatus('score')).toBe('scoring');
  expect(stageToStatus('reframe')).toBe('reframing');
  expect(stageToStatus('caption')).toBe('captioning');
  expect(stageToStatus('banner')).toBe('rendering');
  expect(stageToStatus('publish')).toBe('publishing');
});

// --- buildProgressUpdate ------------------------------------------------

test('buildProgressUpdate on an empty set reports the queued baseline', () => {
  expect(buildProgressUpdate(new Set<Stage>())).toEqual({ status: 'queued', progress: 0 });
});

test('buildProgressUpdate reports the latest completed stage status (partial)', () => {
  const update = buildProgressUpdate(new Set<Stage>(['transcode', 'asr']));
  // Status follows the LAST completed stage in DAG order (asr → transcribing).
  expect(update.status).toBe('transcribing');
  expect(update.progress).toBeGreaterThan(0);
  expect(update.progress).toBeLessThan(100);
});

test('buildProgressUpdate reports done at 100 when every stage is complete', () => {
  expect(buildProgressUpdate(new Set<Stage>(STAGES))).toEqual({ status: 'done', progress: 100 });
});

// --- applyStageCompleted ------------------------------------------------

test('applyStageCompleted records the stage and derives the next status', () => {
  const completed = new Set<Stage>();

  const result = applyStageCompleted('asr', completed);

  expect(result.update.status).toBe('transcribing');
  expect(completed.has('asr')).toBe(true);
});

test('applyStageCompleted is idempotent on a re-delivered completion', () => {
  const completed = new Set<Stage>();

  const first = applyStageCompleted('asr', completed);
  const second = applyStageCompleted('asr', completed);

  expect(second.update).toEqual(first.update);
  expect(completed.size).toBe(1);
});

// --- buildFailureRecord -------------------------------------------------

test('buildFailureRecord wraps a stage and reason into a failure record', () => {
  expect(buildFailureRecord('score', 'OPENROUTER_402: no credits')).toEqual({
    stage: 'score',
    code: 'STAGE_FAILED',
    message: 'OPENROUTER_402: no credits',
  });
});

test('buildFailureRecord preserves an empty reason as an empty message', () => {
  expect(buildFailureRecord('score', '')).toEqual({
    stage: 'score',
    code: 'STAGE_FAILED',
    message: '',
  });
});
