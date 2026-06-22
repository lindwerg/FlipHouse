import { isNotNull } from 'drizzle-orm';
import {
  integer,
  numeric,
  pgEnum,
  pgTable,
  serial,
  text,
  timestamp,
  uniqueIndex,
} from 'drizzle-orm/pg-core';

// P2 Flow-DAG pipeline tables are owned by `@fliphouse/db` (single source of
// truth, also consumed by apps/worker-node). Re-exported here so the one
// Postgres migration chain (drizzle-kit) includes them.
export { clips, costRecords, flowFailures, uploadLedger, uploadStatusEnum } from '@fliphouse/db';

// This file defines the structure of your database tables using the Drizzle ORM.

// To modify the database schema:
// 1. Update this file with your desired changes.
// 2. Generate a new migration by running: `npm run db:generate`

// The generated migration file will reflect your schema changes.
// It automatically run the command `db-server:file`, which apply the migration before Next.js starts in development mode,
// Alternatively, if your database is running, you can run `npm run db:migrate` and there is no need to restart the server.

// Need a database for production? Check out https://get.neon.com/BMFYNtx
// Tested and compatible with SaaS Boilerplate

// NOTE: FlipHouse has no organizations (founder decision 2026-06-15). A user's
// role (creator/advertiser) lives on the Clerk user's publicMetadata, not in
// the DB — see src/libs/accountType.ts. The org table from P1.10 was removed.

export const todoSchema = pgTable('todo', {
  id: serial('id').primaryKey(),
  ownerId: text('owner_id').notNull(),
  title: text('title').notNull(),
  message: text('message').notNull(),
  updatedAt: timestamp('updated_at', { mode: 'date' })
    .defaultNow()
    .$onUpdate(() => new Date())
    .notNull(),
  createdAt: timestamp('created_at', { mode: 'date' }).defaultNow().notNull(),
});

// Crypto prepaid-balance billing (P1.12). State lives on the Clerk userId — there
// are no organizations. `subscription` is the per-user billing row; `balance_entries`
// is the append-only ledger of credits (deposits) and debits (PAYG / subscription),
// idempotent by (userId, jobId) for PAYG and by txid for on-chain deposits.

export const planEnum = pgEnum('plan', [
  'free',
  'start',
  'active',
  'studio',
  'payg',
]);

export const subscriptionStatusEnum = pgEnum('subscription_status', [
  'active',
  'past_due',
  'canceled',
]);

export const balanceEntryKindEnum = pgEnum('balance_entry_kind', [
  'deposit',
  'payg',
  'subscription',
]);

export const subscriptionSchema = pgTable(
  'subscription',
  {
    userId: text('user_id').primaryKey(),
    plan: planEnum('plan').default('free').notNull(),
    balanceUsdt: numeric('balance_usdt', { precision: 20, scale: 6 })
      .default('0')
      .notNull(),
    depositAddress: text('deposit_address'),
    // Sequential BIP44 derivation index for the HD deposit address (P1.13.1).
    // Allocated max+1 per user so the wallet is recoverable by scanning
    // m/44'/195'/0'/0/0..N. NULL until the address is first derived.
    depositIndex: integer('deposit_index'),
    subscriptionStatus: subscriptionStatusEnum('subscription_status'),
    currentPeriodEnd: timestamp('current_period_end', { mode: 'date' }),
    minutesUsedThisPeriod: integer('minutes_used_this_period')
      .default(0)
      .notNull(),
    updatedAt: timestamp('updated_at', { mode: 'date' })
      .defaultNow()
      .$onUpdate(() => new Date())
      .notNull(),
    createdAt: timestamp('created_at', { mode: 'date' }).defaultNow().notNull(),
  },
  table => [
    // One deposit address maps to exactly one user: the on-chain watcher reverse-
    // maps a transfer's recipient to a userId, so a derivation collision must never
    // credit the wrong user. Partial (WHERE NOT NULL) so users without an address yet
    // (multiple NULLs) don't collide (P1.13).
    uniqueIndex('subscription_deposit_address_uq')
      .on(table.depositAddress)
      .where(isNotNull(table.depositAddress)),
    // One HD index maps to exactly one user — the unique constraint is the
    // collision backstop for concurrent max+1 allocation. Partial (WHERE NOT
    // NULL) so users without an address yet (multiple NULLs) don't collide.
    uniqueIndex('subscription_deposit_index_uq')
      .on(table.depositIndex)
      .where(isNotNull(table.depositIndex)),
  ],
);

export const balanceEntrySchema = pgTable(
  'balance_entries',
  {
    id: serial('id').primaryKey(),
    userId: text('user_id').notNull(),
    kind: balanceEntryKindEnum('kind').notNull(),
    // Signed: positive = credit, negative = debit.
    amountUsdt: numeric('amount_usdt', { precision: 20, scale: 6 }).notNull(),
    jobId: text('job_id'),
    txid: text('txid'),
    reason: text('reason').notNull(),
    createdAt: timestamp('created_at', { mode: 'date' }).defaultNow().notNull(),
  },
  table => [
    // Postgres treats NULLs as distinct, so deposits (no jobId) never collide
    // here, while a retried PAYG job (same userId + jobId) is deduped.
    uniqueIndex('balance_entries_user_job_uq').on(table.userId, table.jobId),
    // An on-chain tx is globally unique → idempotent deposit credit (P1.13).
    uniqueIndex('balance_entries_txid_uq').on(table.txid),
  ],
);
