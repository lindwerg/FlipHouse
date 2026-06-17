import { z } from 'zod';

/**
 * TypeScript/Zod mirror of the Python render contract
 * (`fliphouse_worker/clipping/manifest.py`). The `publish` stage parses the
 * Python-emitted `manifest.json` with these schemas before writing the `clips`
 * table, so a cross-language contract test pins these constants to the Python
 * golden — any drift fails CI rather than corrupting the dashboard.
 *
 * Keys are snake_case to match the JSON the Python side emits verbatim.
 */
export const MANIFEST_SCHEMA_VERSION = 1;
export const ENGINE_NAME = 'fliphouse-cpu-mediapipe-v1';

export const clipEntrySchema = z.object({
  rank: z.number().int().nonnegative(),
  score: z.number(),
  sub_scores: z.record(z.string(), z.number().int()),
  confidence: z.number().int(),
  start_time: z.number(),
  end_time: z.number(),
  duration_s: z.number(),
  width: z.number().int().positive(),
  height: z.number().int().positive(),
  path: z.string().min(1),
  title: z.string(),
  used_video: z.boolean(),
  model_used: z.string(),
  modalities_used: z.array(z.string()),
});

export type ClipEntry = z.infer<typeof clipEntrySchema>;

export const renderManifestSchema = z.object({
  schema_version: z.number().int(),
  source: z.string(),
  engine: z.string(),
  generated_at: z.string(),
  resolution: z.array(z.number().int()).length(2),
  clip_count: z.number().int().nonnegative(),
  clips: z.array(clipEntrySchema),
});

export type RenderManifest = z.infer<typeof renderManifestSchema>;

/** Zero-padded clip filename as written by the Python render leg (`clip_000.mp4`). */
export function clipFileName(rank: number): string {
  return `clip_${String(rank).padStart(3, '0')}.mp4`;
}

/**
 * Deterministic R2 key for a clip, derived purely from `(contentHash, rank)`.
 * Because it is a pure function, a re-publish UPDATEs the same `clips` row and
 * overwrites the same object instead of orphaning a duplicate (docs blueprint §3.5).
 */
export function deriveClipKey(contentHash: string, rank: number): string {
  return `clips/${contentHash}/${clipFileName(rank)}`;
}
