import type { ClipDashboardRow } from '@fliphouse/db';
import type { ClipView } from './api-schemas';
import { toClipUrl } from './url';

// Projection from the DB row (numeric columns as strings, clipUrl as an R2 object
// key) to the ClipView the dashboard renders (numbers + a playable URL). Async
// because the clip bucket is private — the URL is a server-side presign (P2.3).
// Kept thin so the /clips route stays an auth+fetch shell — unit-tested 100%.

/**
 * Maps a stored clip row to its dashboard view, coercing numeric-string columns
 * to numbers and resolving the stored R2 object key to a presigned playback URL.
 * Async: the presign is a server-side AWS call (see {@link toClipUrl}).
 */
export async function toClipView(row: ClipDashboardRow): Promise<ClipView> {
  return {
    rank: row.rank,
    score: Number(row.score),
    startTime: Number(row.startTime),
    endTime: Number(row.endTime),
    durationS: Number(row.durationS),
    width: row.width,
    height: row.height,
    clipUrl: await toClipUrl(row.clipUrl),
    title: row.title,
  };
}
