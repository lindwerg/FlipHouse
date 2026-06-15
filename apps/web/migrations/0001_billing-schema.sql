CREATE TYPE "public"."balance_entry_kind" AS ENUM('deposit', 'payg', 'subscription');--> statement-breakpoint
CREATE TYPE "public"."plan" AS ENUM('free', 'start', 'active', 'studio', 'payg');--> statement-breakpoint
CREATE TYPE "public"."subscription_status" AS ENUM('active', 'past_due', 'canceled');--> statement-breakpoint
CREATE TABLE "balance_entries" (
	"id" serial PRIMARY KEY NOT NULL,
	"user_id" text NOT NULL,
	"kind" "balance_entry_kind" NOT NULL,
	"amount_usdt" numeric(20, 6) NOT NULL,
	"job_id" text,
	"txid" text,
	"reason" text NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "subscription" (
	"user_id" text PRIMARY KEY NOT NULL,
	"plan" "plan" DEFAULT 'free' NOT NULL,
	"balance_usdt" numeric(20, 6) DEFAULT '0' NOT NULL,
	"deposit_address" text,
	"subscription_status" "subscription_status",
	"current_period_end" timestamp,
	"minutes_used_this_period" integer DEFAULT 0 NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX "balance_entries_user_job_uq" ON "balance_entries" USING btree ("user_id","job_id");--> statement-breakpoint
CREATE UNIQUE INDEX "balance_entries_txid_uq" ON "balance_entries" USING btree ("txid");