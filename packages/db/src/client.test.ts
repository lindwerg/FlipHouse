import type { Pool } from 'pg';
import { expect, test } from 'vitest';

import { createDb } from './client.js';

test('createDb wraps a pg Pool into a drizzle handle', () => {
  const pool = {} as unknown as Pool;
  const db = createDb(pool);

  expect(typeof db.select).toBe('function');
  expect(typeof db.insert).toBe('function');
});
