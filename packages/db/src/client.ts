import { drizzle } from 'drizzle-orm/node-postgres';
import type { NodePgDatabase } from 'drizzle-orm/node-postgres';
import type { Pool } from 'pg';

import * as schema from './schema.js';

/** Drizzle database handle bound to the pipeline schema. */
export type Db = NodePgDatabase<typeof schema>;

/** Build a drizzle client over a node-postgres Pool (production wiring). */
export function createDb(pool: Pool): Db {
  return drizzle(pool, { schema });
}
