ALTER TABLE "flow_failures" ADD COLUMN "owner_id" text;--> statement-breakpoint
CREATE INDEX "flow_failures_owner_hash_idx" ON "flow_failures" USING btree ("owner_id","content_hash");