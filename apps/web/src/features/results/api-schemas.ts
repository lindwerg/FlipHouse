import type { UploadStatus } from '@fliphouse/db';
import * as z from 'zod';
import { UPLOAD_STATUSES } from './upload-status';

// Zod boundary schemas for the results dashboard routes (P2.3). Validate the
// contentHash path param, and shape the /clips + /progress JSON payloads. Pure —
// unit-tested at 100%; the routes parse with these so no `any` crosses the wire.

const uploadStatusValues = UPLOAD_STATUSES as [UploadStatus, ...UploadStatus[]];

// z.enum over the shared enum values: runtime-validates an unknown string while
// narrowing the inferred type to the exact UploadStatus union.
const uploadStatusSchema = z.enum(uploadStatusValues);

/** 64-char lowercase hex SHA-256 — the same identity the upload pipeline uses. */
export const contentHashParamSchema = z
  .string()
  .regex(/^[0-9a-f]{64}$/, 'contentHash must be a 64-char lowercase hex sha256');

/** One ranked clip as the dashboard renders it (numeric fields coerced). */
export const clipViewSchema = z.object({
  rank: z.number().int().min(0),
  score: z.number(),
  startTime: z.number(),
  endTime: z.number(),
  durationS: z.number(),
  width: z.number().int().positive(),
  height: z.number().int().positive(),
  clipUrl: z.string().url(),
  title: z.string(),
});

export type ClipView = z.infer<typeof clipViewSchema>;

/** GET /clips 200 body. */
export const clipsResponseSchema = z.object({
  status: uploadStatusSchema,
  clips: z.array(clipViewSchema),
});

export type ClipsResponse = z.infer<typeof clipsResponseSchema>;

/** One SSE progress event payload. */
export const progressResponseSchema = z.object({
  status: uploadStatusSchema,
  percent: z.number().min(0).max(100),
  label: z.string(),
  isTerminal: z.boolean(),
});

export type ProgressResponse = z.infer<typeof progressResponseSchema>;
