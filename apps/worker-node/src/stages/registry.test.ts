import { expect, test } from 'vitest';

import { executeStage } from './execute-stage.js';
import { isPythonStage, resolveStageHandler } from './registry.js';

test('python-backed stages resolve to the generic executeStage handler', () => {
  expect(isPythonStage('transcode')).toBe(true);
  expect(resolveStageHandler('score')).toBe(executeStage);
});

test('publish is not a generic python stage and is rejected here', () => {
  expect(isPythonStage('publish')).toBe(false);
  expect(() => resolveStageHandler('publish')).toThrow(/no generic stage handler/);
});
