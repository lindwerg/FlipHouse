import { pgEnum, pgTable, serial, text, timestamp } from 'drizzle-orm/pg-core';

// This file defines the structure of your database tables using the Drizzle ORM.

// To modify the database schema:
// 1. Update this file with your desired changes.
// 2. Generate a new migration by running: `npm run db:generate`

// The generated migration file will reflect your schema changes.
// It automatically run the command `db-server:file`, which apply the migration before Next.js starts in development mode,
// Alternatively, if your database is running, you can run `npm run db:migrate` and there is no need to restart the server.

// Need a database for production? Check out https://get.neon.com/BMFYNtx
// Tested and compatible with SaaS Boilerplate

// FlipHouse account type for an organization (docs/01 §1 — `accountType` on
// teams). An org is either a content creator or an advertiser; null until the
// onboarding step (P1.11) sets it. Stripe/billing columns land in P1.12–P1.13.
export const accountTypeEnum = pgEnum('account_type', ['creator', 'advertiser']);

export const organizationSchema = pgTable('organization', {
  // Clerk organization id (e.g. `org_…`); the org is created by Clerk, we mirror
  // its id here to attach FlipHouse-owned columns.
  id: text('id').primaryKey(),
  accountType: accountTypeEnum('account_type'),
  updatedAt: timestamp('updated_at', { mode: 'date' })
    .defaultNow()
    .$onUpdate(() => new Date())
    .notNull(),
  createdAt: timestamp('created_at', { mode: 'date' }).defaultNow().notNull(),
});

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
