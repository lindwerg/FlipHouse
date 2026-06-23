import { lookup } from 'node:dns/promises';

import { isBlockedHost } from '@fliphouse/shared';

import { IngestDownloadError } from './ytdlp-download.js';

/**
 * Worker-side SSRF guard — the async second line of defence behind the shared
 * `isBlockedHost` literal-host check. It DNS-resolves the URL host and re-checks
 * EVERY resolved address against the private/loopback/link-local/metadata ranges,
 * so a public-looking name that resolves to an internal IP (DNS-rebinding) is
 * blocked BEFORE yt-dlp is spawned.
 *
 * Note: yt-dlp re-resolves DNS itself and follows redirects, so this guard alone
 * cannot pin the exact socket yt-dlp opens. It is paired with the yt-dlp
 * `--max-filesize` ceiling (DoS) and is the best-effort pre-flight reject; the
 * literal-host gate in `isIngestableUrl` already covers every literal private
 * target. A blocked resolution surfaces as the same loud, classified
 * {@link IngestDownloadError} the rest of ingestion uses.
 */

/** Russian, user-facing copy for a URL whose host resolves to a blocked address. */
const BLOCKED_HOST_MESSAGE =
  'Эта ссылка ведёт на внутренний адрес и не может быть загружена. Пришлите публичную ссылку на видео.';

/** The DNS-resolution seam, injectable so the guard is unit-tested with no real DNS. */
export type LookupFn = (hostname: string) => Promise<ReadonlyArray<{ address: string }>>;

/* v8 ignore start -- real DNS I/O; covered by the injected lookup seam */
const defaultLookup: LookupFn = (hostname) => lookup(hostname, { all: true });
/* v8 ignore stop */

/** Strip surrounding brackets an IPv6 URL host carries (`[::1]` → `::1`). */
function unbracket(host: string): string {
  return host.startsWith('[') && host.endsWith(']') ? host.slice(1, -1) : host;
}

/**
 * Assert that `url`'s host is safe to fetch server-side: reject a blocked literal
 * host, then DNS-resolve and reject if ANY resolved address is private/internal.
 * Throws a loud {@link IngestDownloadError} (kind `private`) on a blocked target;
 * resolves silently when every address is public. A DNS-resolution failure is NOT
 * fatal here (the host may still be a literal IP or yt-dlp may resolve it) — only
 * a positively-blocked address rejects.
 */
export async function assertPublicUrl(url: string, lookupFn: LookupFn = defaultLookup): Promise<void> {
  let host: string;
  try {
    host = unbracket(new URL(url).hostname);
  } catch {
    throw new IngestDownloadError('unknown', BLOCKED_HOST_MESSAGE, `unparseable ingest url: ${url}`);
  }

  if (isBlockedHost(host)) {
    throw new IngestDownloadError('private', BLOCKED_HOST_MESSAGE, `blocked literal host: ${host}`);
  }

  // A literal IP needs no DNS round-trip — the literal check above already cleared it.
  let resolved: ReadonlyArray<{ address: string }>;
  try {
    resolved = await lookupFn(host);
  } catch {
    // DNS failure is not proof of a private target; let yt-dlp surface a real
    // download error if the host is genuinely unreachable.
    return;
  }

  const blocked = resolved.find((entry) => isBlockedHost(entry.address));
  if (blocked) {
    throw new IngestDownloadError(
      'private',
      BLOCKED_HOST_MESSAGE,
      `host ${host} resolves to blocked address ${blocked.address}`,
    );
  }
}
