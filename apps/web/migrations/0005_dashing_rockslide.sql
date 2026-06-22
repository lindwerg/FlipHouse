CREATE TABLE "cost_records" (
	"id" serial PRIMARY KEY NOT NULL,
	"content_hash" text NOT NULL,
	"owner_id" text NOT NULL,
	"cost_usd_micros" bigint NOT NULL,
	"engine" text,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX "cost_records_content_hash_uq" ON "cost_records" USING btree ("content_hash");