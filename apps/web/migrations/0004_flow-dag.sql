CREATE TYPE "public"."upload_status" AS ENUM('queued', 'hashing', 'transcoding', 'transcribing', 'scoring', 'reframing', 'captioning', 'rendering', 'storing', 'publishing', 'done', 'failed', 'duplicate');--> statement-breakpoint
CREATE TABLE "clips" (
	"id" serial PRIMARY KEY NOT NULL,
	"content_hash" text NOT NULL,
	"rank" integer NOT NULL,
	"score" numeric(6, 4) NOT NULL,
	"sub_scores" jsonb NOT NULL,
	"confidence" integer NOT NULL,
	"start_time" numeric(10, 3) NOT NULL,
	"end_time" numeric(10, 3) NOT NULL,
	"duration_s" numeric(10, 3) NOT NULL,
	"width" integer NOT NULL,
	"height" integer NOT NULL,
	"clip_url" text NOT NULL,
	"title" text NOT NULL,
	"used_video" boolean NOT NULL,
	"model_used" text NOT NULL,
	"modalities_used" jsonb NOT NULL,
	"manifest_schema_version" integer NOT NULL,
	"engine" text NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "flow_failures" (
	"id" serial PRIMARY KEY NOT NULL,
	"content_hash" text NOT NULL,
	"stage" text NOT NULL,
	"code" text NOT NULL,
	"message" text NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "upload_ledger" (
	"content_hash" text PRIMARY KEY NOT NULL,
	"owner_id" text NOT NULL,
	"first_upload_id" text NOT NULL,
	"tus_object_key" text NOT NULL,
	"status" "upload_status" DEFAULT 'queued' NOT NULL,
	"flow_job_id" text,
	"size_bytes" integer,
	"duration_sec" integer,
	"result_url" text,
	"manifest_url" text,
	"engine" text,
	"error" text,
	"attempts" integer DEFAULT 0 NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX "clips_hash_rank_uq" ON "clips" USING btree ("content_hash","rank");