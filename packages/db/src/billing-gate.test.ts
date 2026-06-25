import { PGlite } from '@electric-sql/pglite';
import { sql } from 'drizzle-orm';
import { drizzle } from 'drizzle-orm/pglite';
import { afterEach, beforeEach, expect, test } from 'vitest';

import { BillingError, assertAffordable, resolveMinuteCap } from './billing-gate.js';
import type { Db } from './client.js';
import * as schema from './schema.js';

const DDL = `
CREATE TYPE plan AS ENUM ('free','start','active','studio','payg');
CREATE TYPE subscription_status AS ENUM ('active','past_due','canceled');
CREATE TABLE subscription (
  user_id text PRIMARY KEY,
  plan plan NOT NULL DEFAULT 'free',
  balance_usdt numeric(20,6) NOT NULL DEFAULT '0',
  deposit_address text,
  deposit_index integer,
  subscription_status subscription_status,
  current_period_end timestamp,
  minutes_used_this_period integer NOT NULL DEFAULT 0,
  updated_at timestamp NOT NULL DEFAULT now(),
  created_at timestamp NOT NULL DEFAULT now()
);
`;

let client: PGlite;
let db: Db;

beforeEach(async () => {
  client = new PGlite();
  await client.exec(DDL);
  db = drizzle({ client, schema }) as unknown as Db;
});

afterEach(async () => {
  await client.close();
});

async function seed(
  userId: string,
  plan: string,
  balanceUsdt: string,
  minutesUsed = 0,
): Promise<void> {
  await db.execute(sql`
    INSERT INTO subscription (user_id, plan, balance_usdt, minutes_used_this_period)
    VALUES (${userId}, ${sql.raw(`'${plan}'`)}, ${balanceUsdt}, ${minutesUsed})
  `);
}

test('PAYG: passes when the balance covers the per-minute cost', async () => {
  await seed('u', 'payg', '1.000000'); // $1.00 covers 2 min ($0.50)
  await expect(assertAffordable(db, 'u', 90, {})).resolves.toBeUndefined();
});

test('PAYG: blocks insufficient_balance when the balance is below cost', async () => {
  await seed('u', 'payg', '0.250000'); // $0.25 < 2 min ($0.50)
  await expect(assertAffordable(db, 'u', 90, {})).rejects.toMatchObject({
    reason: 'insufficient_balance',
  });
});

test('PAYG: exact balance == cost is allowed (no float drift on the boundary)', async () => {
  await seed('u', 'payg', '0.500000'); // exactly 2 min
  await expect(assertAffordable(db, 'u', 120, {})).resolves.toBeUndefined();
});

test('PAYG: a fractional-micro balance just under cost is blocked (integer compare)', async () => {
  await seed('u', 'payg', '0.499999'); // one micro short of $0.50
  await expect(assertAffordable(db, 'u', 120, {})).rejects.toBeInstanceOf(BillingError);
});

test('subscription: passes when within the monthly minute cap', async () => {
  await seed('u', 'start', '0', 100); // start cap 150; +1 min (1s → floor) → 101 ≤ 150
  await expect(assertAffordable(db, 'u', 1, {})).resolves.toBeUndefined();
});

test('subscription: blocks minute_cap_exceeded when the job would overflow the cap', async () => {
  await seed('u', 'start', '0', 149); // start cap 150; +2 min → 151 > 150
  await expect(assertAffordable(db, 'u', 61, {})).rejects.toMatchObject({
    reason: 'minute_cap_exceeded',
  });
});

test('no subscription row → free plan, capped at 30 minutes', async () => {
  // free cap 30; used 0; a 31-min source overflows.
  await expect(assertAffordable(db, 'ghost', 31 * 60, {})).rejects.toMatchObject({
    reason: 'minute_cap_exceeded',
  });
  // ...but a 30-min source is exactly at the cap and allowed.
  await expect(assertAffordable(db, 'ghost', 30 * 60, {})).resolves.toBeUndefined();
});

test('resolveMinuteCap honours a BILLING_PLAN_ENV override and falls open on malformed JSON', () => {
  const env = { BILLING_PLAN_ENV: JSON.stringify({ start: { minutesPerMonth: 500 } }) };
  expect(resolveMinuteCap('start', env)).toBe(500);
  expect(resolveMinuteCap('active', env)).toBe(300); // untouched default (plan key absent in override)
  // payg has no cap by default.
  expect(resolveMinuteCap('payg', {})).toBeNull();
  // An override that explicitly removes a plan's cap (minutesPerMonth: null) is honoured.
  expect(
    resolveMinuteCap('start', { BILLING_PLAN_ENV: JSON.stringify({ start: { minutesPerMonth: null } }) }),
  ).toBeNull();
  // An override object present but WITHOUT minutesPerMonth → default (key-check guard).
  expect(
    resolveMinuteCap('start', { BILLING_PLAN_ENV: JSON.stringify({ start: { priceUsdt: 9 } }) }),
  ).toBe(150);
  // No override env at all → default.
  expect(resolveMinuteCap('active', {})).toBe(300);
  // Malformed override → default (never wedges the pipeline).
  expect(resolveMinuteCap('start', { BILLING_PLAN_ENV: 'not json' })).toBe(150);
});

test('subscription cap respects a BILLING_PLAN_ENV override', async () => {
  await seed('u', 'start', '0', 200); // default cap 150 would block at 200...
  const env = { BILLING_PLAN_ENV: JSON.stringify({ start: { minutesPerMonth: 500 } }) };
  // ...but the override raises it to 500, so +1 min is allowed.
  await expect(assertAffordable(db, 'u', 1, env)).resolves.toBeUndefined();
});
