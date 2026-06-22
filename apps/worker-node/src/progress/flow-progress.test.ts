import { STAGES } from '@fliphouse/shared';
import { expect, test } from 'vitest';

import { computeFlowProgress } from './flow-progress.js';

test('no completed stages is 0%', () => {
  expect(computeFlowProgress([])).toBe(0);
});

test('all stages completed is 100%', () => {
  expect(computeFlowProgress(STAGES)).toBe(100);
});

test('progress is monotonic as stages accumulate', () => {
  const afterTranscode = computeFlowProgress(['transcode']);
  const afterScore = computeFlowProgress(['transcode', 'asr', 'score']);

  expect(afterScore).toBeGreaterThan(afterTranscode);
  expect(afterTranscode).toBeGreaterThan(0);
});

test('duplicate stages in the input do not inflate progress', () => {
  expect(computeFlowProgress(['transcode', 'transcode'])).toBe(computeFlowProgress(['transcode']));
});
