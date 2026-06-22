import { z } from 'zod';

/**
 * Incoming GPU-callback contract (spec §6.12). The GPU caller is FlipHouse's OWN
 * Modal/custom code (NOT a third-party Replicate model), so this is our own
 * scheme — a small JSON body signed with HMAC-SHA256 over the raw bytes (see
 * verify-hmac.ts). The caller POSTs a prediction outcome: an `id` (the prediction
 * id we parked the job under), a terminal `status`, and either `output` (on
 * success) or `error` (on failure). Invariant: the body is fully validated into
 * this strict shape BEFORE any state mutation, so a malformed callback fails
 * closed (ZodError) instead of half-resuming a job. All fields are read-only —
 * the parsed value is never mutated downstream. (If a real Replicate model ever
 * becomes the source, it signs via Svix — 3 headers, not this `sha256=<hex>` —
 * and verify-hmac.ts must be swapped, not extended.)
 */
export const gpuCallbackSchema = z.object({
  id: z.string().min(1),
  status: z.enum(['succeeded', 'failed', 'canceled']),
  output: z.unknown().nullable().default(null),
  error: z.string().nullable().default(null),
  version: z.string().optional(),
});

export type GpuCallback = z.infer<typeof gpuCallbackSchema>;
