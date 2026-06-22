import { z } from 'zod';

/**
 * TypeScript/Zod mirror of the Python render contract
 * (`fliphouse_worker/clipping/manifest.py`, schema v2). The `publish` stage
 * parses the Python-emitted `manifest.json` with these schemas before writing
 * the `clips` table. The contract is pinned by a REAL cross-language golden
 * (`manifest-contract.golden.json`, a verbatim copy of the Python
 * `RenderManifest.to_dict()` byte-shape): the TS test round-trips the golden and
 * the Python `test_golden_matches_shared` asserts its live output still equals
 * it — so any drift in either language fails CI, not the dashboard.
 *
 * `.passthrough()` is set on BOTH schemas so an unknown field the Python side
 * adds survives the round-trip and surfaces as a golden mismatch (drift signal)
 * rather than being silently stripped. Keys are snake_case to match the JSON
 * the Python side emits verbatim.
 */
export const MANIFEST_SCHEMA_VERSION = 2;
export const ENGINE_NAME = 'fliphouse-cpu-mediapipe-v1';

export const clipEntrySchema = z
  .object({
    rank: z.number().int().nonnegative(),
    score: z.number(),
    sub_scores: z.record(z.string(), z.number().int()),
    confidence: z.number().int(),
    start_time: z.number(),
    end_time: z.number(),
    duration_s: z.number(),
    width: z.number().int().positive(),
    height: z.number().int().positive(),
    // A bare 2-digit filename only — `publish` concatenates this onto the
    // clips prefix (the caption stage's output) to build the R2 key, so anything
    // else (path traversal, absolute key) must be rejected at the contract boundary.
    path: z.string().regex(/^clip_\d{2}\.mp4$/, 'clip path must be a bare 2-digit filename'),
    title: z.string(),
    used_video: z.boolean(),
    model_used: z.string(),
    modalities_used: z.array(z.string()),
    // v2 fields; `.default()` keeps a v1-shaped manifest parseable.
    segment_count: z.number().int().positive().default(1),
    caption_band: z.record(z.string(), z.number()).nullable().default(null),
  })
  .passthrough();

export type ClipEntry = z.infer<typeof clipEntrySchema>;

export const renderManifestSchema = z
  .object({
    schema_version: z.number().int(),
    source: z.string(),
    engine: z.string(),
    generated_at: z.string(),
    resolution: z.array(z.number().int()).length(2),
    clip_count: z.number().int().nonnegative(),
    clips: z.array(clipEntrySchema),
  })
  .passthrough();

export type RenderManifest = z.infer<typeof renderManifestSchema>;

/**
 * Zero-padded clip filename as written by the Python render leg
 * (`clip_00.mp4`). 2-digit pad matches Python `crop_geometry.clip_filename`
 * (`f"clip_{rank:02d}.mp4"`); top-N keeps N well below 100.
 */
export function clipFileName(rank: number): string {
  return `clip_${String(rank).padStart(2, '0')}.mp4`;
}

/**
 * Deterministic R2 key for a clip, derived purely from `(contentHash, rank)`.
 * Because it is a pure function, a re-publish UPDATEs the same `clips` row and
 * overwrites the same object instead of orphaning a duplicate (docs blueprint §3.5).
 */
export function deriveClipKey(contentHash: string, rank: number): string {
  return `clips/${contentHash}/${clipFileName(rank)}`;
}
