import { describe, expect, test } from 'vitest';

import { buildHealthPayload } from './health.js';

describe('buildHealthPayload', () => {
  test('buildHealthPayload returns ok status for web service', () => {
    expect(buildHealthPayload()).toEqual({ status: 'ok', service: 'web' });
  });
});
