import { Env } from '@/libs/Env';

// Single seam that turns a stored R2 object key into a browser-playable URL
// (P2.3). Centralising it here means swapping a public bucket for a presigned
// route (founder-gated) is a one-file change. Pure given the env — unit-tested.

/**
 * Builds a clip's public URL from its stored R2 object key:
 * `${NEXT_PUBLIC_R2_PUBLIC_BASE}/${key}`. A leading slash on the key (or a
 * trailing slash on the base) is normalised so the result never doubles `//`.
 */
export function toClipUrl(key: string): string {
  const base = Env.NEXT_PUBLIC_R2_PUBLIC_BASE.replace(/\/+$/, '');
  const normalisedKey = key.replace(/^\/+/, '');
  return `${base}/${normalisedKey}`;
}
