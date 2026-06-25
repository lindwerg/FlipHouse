import { expect, test } from 'vitest';

import { createLogger } from './log.js';

test('createLogger defaults to info level and tags the worker-node service', () => {
  const logger = createLogger({});
  expect(logger.level).toBe('info');
  // pino stamps the `base` fields onto every line; assert the service tag is bound.
  expect(logger.bindings()).toMatchObject({ service: 'worker-node' });
});

test('createLogger honours LOG_LEVEL', () => {
  expect(createLogger({ LOG_LEVEL: 'debug' }).level).toBe('debug');
  expect(createLogger({ LOG_LEVEL: 'warn' }).level).toBe('warn');
});
