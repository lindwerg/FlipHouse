import { z } from 'zod';

/**
 * Incoming GigaAM-v3 ASR callback contract (P2 step #1, TRACK B). The GPU caller
 * is FlipHouse's OWN GigaAM-v3 transcription worker (NOT a third-party Replicate
 * model), so this is our own scheme — a small JSON body signed with HMAC-SHA256
 * over `${timestamp}.${rawBody}` (see verify-hmac.ts) with a ±300s replay window.
 *
 * The body is a discriminated union on `status`:
 *   - `succeeded`: carries the full transcription `payload` (duration, language,
 *     word-timestamped segments). This is the object we persist verbatim to R2
 *     before enqueuing the `asr-resume` job.
 *   - `failed`: carries a provider `error` string; the parked job is failed.
 *
 * Invariant: the body is fully validated into this strict shape BEFORE any state
 * mutation, so a malformed callback fails closed (ZodError) instead of
 * half-resuming a job. All fields are read-only — the parsed value is never
 * mutated downstream.
 */

/** A single word with its in-clip timestamps (seconds). */
export const wordSegmentSchema = z.object({
  word: z.string(),
  start: z.number(),
  end: z.number(),
});

/**
 * A transcription segment: a span of audio with its constituent words.
 *
 * `text` is the model's PUNCTUATED/normalized segment transcription (GigaAM v3
 * `e2e_rnnt` emits punctuation at the segment level, not on the bare per-word
 * tokens — TRANS-1). It is OPTIONAL/additive so a legacy payload still validates;
 * it MUST be retained verbatim here because Zod strips unknown keys, and the
 * parsed payload is what is persisted to R2 — dropping `text` would discard the
 * only native sentence-boundary signal the worker has.
 */
export const transcriptSegmentSchema = z.object({
  start: z.number(),
  end: z.number(),
  text: z.string().optional(),
  words: z.array(wordSegmentSchema),
});

/** The GigaAM-v3 transcription result, persisted verbatim to R2 on success. */
export const asrPayloadSchema = z.object({
  duration: z.number(),
  language: z.literal('ru'),
  segments: z.array(transcriptSegmentSchema),
});

const succeededSchema = z.object({
  request_id: z.string().uuid(),
  status: z.literal('succeeded'),
  engine: z.literal('gigaam-v3'),
  payload: asrPayloadSchema,
});

const failedSchema = z.object({
  request_id: z.string().uuid(),
  status: z.literal('failed'),
  error: z.string(),
});

/** The full callback body — a discriminated union on `status`. */
export const gpuCallbackSchema = z.discriminatedUnion('status', [succeededSchema, failedSchema]);

export type WordSegment = z.infer<typeof wordSegmentSchema>;
export type TranscriptSegment = z.infer<typeof transcriptSegmentSchema>;
export type AsrPayload = z.infer<typeof asrPayloadSchema>;
export type GpuCallback = z.infer<typeof gpuCallbackSchema>;
export type SucceededCallback = z.infer<typeof succeededSchema>;
export type FailedCallback = z.infer<typeof failedSchema>;
