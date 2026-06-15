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

export const subscriptionSchema = pgTable('subscription', {
  userId: text('user_id').primaryKey(),
  plan: planEnum('plan').default('free').notNull(),
  balanceUsdt: numeric('balance_usdt', { precision: 20, scale: 6 })
    .default('0')
    .notNull(),
  depositAddress: text('deposit_address'),
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
});

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
