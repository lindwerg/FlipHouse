import { fileURLToPath } from 'node:url';
import { PGlite } from '@electric-sql/pglite';
import { eq, sql } from 'drizzle-orm';
import { drizzle } from 'drizzle-orm/pglite';
import { migrate } from 'drizzle-orm/pglite/migrator';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { organizationSchema } from './Schema';

// Integration test on an ephemeral in-memory PGlite. Each test gets a fresh DB
// with the REAL generated migrations applied (drizzle-orm/pglite migrator), so
// the enum column, its nullability and the migration itself are exercised
// against a Postgres-compatible engine — not a mock.
const migrationsFolder = fileURLToPath(new URL('../../migrations', import.meta.url));

type Db = ReturnType<typeof drizzle>;

let client: PGlite;
let db: Db;

beforeEach(async () => {
  client = new PGlite();
  db = drizzle(client);
  await migrate(db, { migrationsFolder });
});

afterEach(async () => {
  await client.close();
});

describe('organization accountType', () => {
  it('organization schema has accountType enum column', async () => {
    const result = await db.execute(sql`
      select data_type, udt_name
      from information_schema.columns
      where table_name = 'organization' and column_name = 'account_type'
    `);
    const row = result.rows[0] as { data_type: string; udt_name: string } | undefined;

    expect(row).toBeDefined();
    expect(row!.data_type).toBe('USER-DEFINED');
    expect(row!.udt_name).toBe('account_type');
  });

  it('accountType defaults to null until onboarding sets it', async () => {
    await db.insert(organizationSchema).values({ id: 'org_default' });

    const [org] = await db
      .select()
      .from(organizationSchema)
      .where(eq(organizationSchema.id, 'org_default'));

    expect(org!.accountType).toBeNull();
  });

  it('persists and reads back accountType=creator', async () => {
    await db
      .insert(organizationSchema)
      .values({ id: 'org_creator', accountType: 'creator' });

    const [org] = await db
      .select()
      .from(organizationSchema)
      .where(eq(organizationSchema.id, 'org_creator'));

    expect(org!.accountType).toBe('creator');
  });

  it('rejects invalid accountType value', async () => {
    await expect(
      db.execute(
        sql`insert into organization (id, account_type) values ('org_bad', 'admin')`,
      ),
    ).rejects.toThrow();
  });

  it('migration is idempotent (re-run is a no-op)', async () => {
    // beforeEach already migrated once; a second run must not throw or alter.
    await expect(
      migrate(db, { migrationsFolder }),
    ).resolves.not.toThrow();

    await db.insert(organizationSchema).values({ id: 'org_after', accountType: 'advertiser' });
    const [org] = await db
      .select()
      .from(organizationSchema)
      .where(eq(organizationSchema.id, 'org_after'));

    expect(org!.accountType).toBe('advertiser');
  });
});
