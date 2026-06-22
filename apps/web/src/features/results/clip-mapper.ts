import type { ClipDashboardRow } from '@fliphouse/db';
import type { ClipView } from './api-schemas';
import { toClipUrl } from './url';

// Pure projection from the DB row (numeric columns as strings, clipUrl as an R2
// object key) to the ClipView the dashboard renders (numbers + a playable URL).
// Kept pure so the /clips route stays a thin auth+fetch shell — unit-tested 100%.

/** Maps a stored clip row to its dashboard view, coercing numerics + the URL. */
export function toClipView(row: ClipDashboardRow): ClipView {
  return {
    rank: row.rank,
    score: Number(row.score),
    startTime: Number(row.startTime),
    endTime: Number(row.endTime),
    durationS: Number(row.durationS),
    width: row.width,
    height: row.height,
    clipUrl: toClipUrl(row.clipUrl),
    title: row.title,
  };
}
