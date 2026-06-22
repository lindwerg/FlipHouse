import { presignClipUrl } from './r2-presign';

// Single seam that turns a stored R2 object key into a browser-playable URL
// (P2.3). The clip bucket is now private-read, so this is an async server-side
// presign (see r2-presign.ts) rather than a public-base concat. Centralising it
// here keeps the swap a one-import change for callers (clip-mapper).

/**
 * Resolves a stored R2 object key (e.g. `clips/<hash>/rank-1.mp4`) to a
 * short-lived presigned GET URL the browser can play/download. A leading slash
 * on the key is normalised by {@link presignClipUrl}. Async — presigning needs
 * server credentials + node crypto, so the /clips route runs on the Node runtime.
 */
export async function toClipUrl(key: string): Promise<string> {
  return presignClipUrl(key);
}
