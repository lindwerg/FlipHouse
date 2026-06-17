import { z } from 'zod';

/**
 * tusd `post-finish` hook envelope (the only hook type we act on). All
 * `MetaData` values are strings (tus metadata is string-valued). We validate at
 * the boundary and read `sha256` (client-streamed content hash) + `ownerId`.
 */
export const tusdPostFinishSchema = z.object({
  Type: z.literal('post-finish'),
  Event: z.object({
    Upload: z.object({
      ID: z.string().min(1),
      Size: z.number().int().nonnegative(),
      MetaData: z.record(z.string(), z.string()),
      Storage: z.object({
        Bucket: z.string(),
        Key: z.string().min(1),
      }),
    }),
  }),
});

export type TusdPostFinish = z.infer<typeof tusdPostFinishSchema>;
